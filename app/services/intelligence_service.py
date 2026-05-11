import concurrent.futures

from celery.utils.log import get_task_logger
from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from app.core.config import settings
from app.schemas.graph_state import IntelligenceState, VideoOverview

logger = get_task_logger(__name__)

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

def _process_single_chunk(chunk):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 유튜브 영상 텍스트 조각을 요약하는 AI다. "
                        "핵심 인사이트와 정보 중심으로 2~3문장으로 간결하게 요약한다. "
                        "불필요한 인트로, 인사, 광고 문구는 제외한다."
                    ),
                },
                {"role": "user", "content": chunk["content"]},
            ],
        )
        summary = response.choices[0].message.content.strip()
        if response.usage:
            logger.info(f"  chunk summary tokens: {response.usage.total_tokens}")
    except Exception as exc:
        logger.warning(
            f"  chunk {chunk.get('chunk_order', '?')} summary failed: {exc}"
        )
        summary = chunk.get("content", "")[:100] + "..."

    logger.info(f"  chunk {chunk.get('chunk_order', '?')} summary done")
    return {**chunk, "summary": summary}


def summarize_each_chunk(state: IntelligenceState) -> dict:
    video_id = state.get("video_id", "Unknown")
    chunks = state.get("chunks", [])

    logger.info(
        f"[LangGraph: chunk summary] start (video_id={video_id}, chunks={len(chunks)})"
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(_process_single_chunk, chunks)
        summarized_chunks = list(results)

    return {"summarized_chunks": summarized_chunks}


def embed_summaries_node(state: IntelligenceState) -> dict:
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])
    texts = [chunk.get("summary", "") for chunk in summarized_chunks]

    logger.info(
        f"[LangGraph: embedding] start (video_id={video_id}, chunks={len(texts)})"
    )

    embeddings = []
    if not texts:
        return {"embeddings": embeddings}

    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        for index, chunk in enumerate(summarized_chunks):
            if index < len(embeddings):
                chunk["embedding"] = embeddings[index]
        if hasattr(response, "usage") and response.usage:
            logger.info(f"  embedding tokens: {response.usage.total_tokens}")
        if embeddings:
            logger.info(f"  embeddings created: {len(embeddings)}, dim={len(embeddings[0])}")
    except Exception as exc:
        logger.error(f"  embedding API failed: {exc}")

    return {"embeddings": embeddings}


def generate_overview(state: IntelligenceState) -> dict:
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])

    all_summaries = "\n".join(
        f"[{chunk.get('chunk_order', '?')}] {chunk.get('summary', '')}"
        for chunk in summarized_chunks
    )

    logger.info(f"[LangGraph: overview] start (video_id={video_id})")

    try:
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "아래는 유튜브 영상의 청크별 요약 목록이다. "
                        "내용을 종합해 영상 전체 제목, 전체 요약, 카테고리를 생성한다. "
                        "요약은 Notion 페이지에 게시할 예정이므로 깔끔하고 읽기 쉽게 작성한다. "
                        "카테고리는 영상의 형식이 아니라 핵심 주제로 분류한다."
                    ),
                },
                {"role": "user", "content": all_summaries},
            ],
            response_format=VideoOverview,
        )
        overview = response.choices[0].message.parsed
        if response.usage:
            logger.info(f"  overview tokens: {response.usage.total_tokens}")
        title = overview.title
        full_summary = overview.full_summary
        category = overview.category
    except Exception as exc:
        logger.warning(f"  overview generation failed: {exc}")
        title = f"영상 {video_id}"
        full_summary = all_summaries[:200]
        category = "미분류"

    logger.info(f"[LangGraph: overview] done title={title}, category={category}")
    return {"title": title, "full_summary": full_summary, "category": category}


def build_intelligence_graph():
    graph = StateGraph(IntelligenceState)
    graph.add_node("summarize_each_chunk", summarize_each_chunk)
    graph.add_node("embed_summaries", embed_summaries_node)
    graph.add_node("generate_overview", generate_overview)
    graph.add_edge(START, "summarize_each_chunk")
    graph.add_edge("summarize_each_chunk", "embed_summaries")
    graph.add_edge("embed_summaries", "generate_overview")
    graph.add_edge("generate_overview", END)
    return graph.compile()


intelligence_graph = build_intelligence_graph()


class IntelligenceService:
    def run(self, data: dict) -> dict:
        result = intelligence_graph.invoke(
            {
                "video_id": data.get("video_id"),
                "chunks": data.get("chunks", []),
                "summarized_chunks": [],
                "embeddings": [],
                "title": "",
                "full_summary": "",
                "category": "",
            }
        )

        return {
            "video_id": data.get("video_id"),
            "metadata": data.get("metadata"),
            "title": result["title"],
            "full_summary": result["full_summary"],
            "category": result["category"],
            "vector_count": len(result.get("embeddings", [])),
            "summarized_chunks": result["summarized_chunks"],
        }
