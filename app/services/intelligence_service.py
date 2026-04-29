# LangGraph node functions
#    - summarize_each_chunk
#    - embed_summaries_node
#    - generate_overview
# build_intelligence_graph()
# intelligence_graph = build_intelligence_graph()
# IntelligenceService class

from app.schemas.graph_state import IntelligenceState, VideoOverview
from celery.utils.log import get_task_logger
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from app.core.config import settings

logger = get_task_logger(__name__)

# OpenAI 클라이언트
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


# ==========================================
# LangGraph node functions
#    - summarize_each_chunk
#    - embed_summaries_node
#    - generate_overview
# ==========================================


# ==========================================
# LangGraph 노드 1: 청크별 요약
# ==========================================
def summarize_each_chunk(state: IntelligenceState) -> dict:
    """각 청크의 content를 OpenAI로 요약"""
    video_id = state.get("video_id", "Unknown")
    chunks = state.get("chunks", [])

    logger.info(
        f"[LangGraph: 청크별 요약] 시작 (video_id: {video_id}, 청크 수: {len(chunks)})"
    )

    summarized_chunks = []
    for chunk in chunks:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 유튜브 영상의 텍스트 조각을 요약하는 AI야. "
                            "핵심 인사이트와 정보 위주로 2~3문장으로 간결하게 요약해. "
                            "불필요한 인트로, 인사말, 광고 문구는 무시해."
                        ),
                    },
                    {"role": "user", "content": chunk["content"]},
                ],
            )
            summary = response.choices[0].message.content.strip()
            if response.usage:
                logger.info(f"  [토큰 사용량] 청크 요약: {response.usage.total_tokens}")
        except Exception as e:
            logger.warning(f"  청크 {chunk.get('chunk_order', '?')} 요약 실패: {e}")
            summary = chunk.get("content", "")[:100] + "..."

        summarized_chunks.append({**chunk, "summary": summary})
        # logger.info(f"  청크 요약 내용 {summarized_chunks}")
        logger.info(f"  청크 {chunk.get('chunk_order', '?')} 요약 완료")

    return {"summarized_chunks": summarized_chunks}


# ==========================================
# LangGraph 노드 2: 요약문 벡터화
# ==========================================
def embed_summaries_node(state: IntelligenceState) -> dict:
    """청크별 요약문을 OpenAI Embeddings로 벡터화"""
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])
    texts = [chunk.get("summary", "") for chunk in summarized_chunks]

    logger.info(
        f"[LangGraph: 벡터화] 시작 (video_id: {video_id}, 청크 수: {len(texts)})"
    )

    embeddings = []
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        for i, chunk in enumerate(summarized_chunks):
            if i < len(embeddings):
                # 각 청크 딕셔너리에 'embedding' 키를 새로 만들어서 숫자 리스트를 넣기
                chunk["embedding"] = embeddings[i]
        if hasattr(response, "usage") and response.usage:
            logger.info(f"  [토큰 사용량] 임베딩: {response.usage.total_tokens}")
        logger.info(f"  벡터 {len(embeddings)}개 생성 (차원: {len(embeddings[0])})")
    except Exception as e:
        logger.error(f"  Embedding API 호출 실패: {e}")

    return {"embeddings": embeddings}


# ==========================================
# LangGraph 노드 3: 전체 개요 생성 (노션 업로드용)
# ==========================================
def generate_overview(state: IntelligenceState) -> dict:
    """청크별 요약을 종합하여 영상 전체 제목/개요/카테고리 생성"""
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])

    all_summaries = "\n".join(
        [
            f"[{c.get('chunk_order', '?')}] {c.get('summary', '')}"
            for c in summarized_chunks
        ]
    )

    logger.info(f"[LangGraph: 개요 생성] 시작 (video_id: {video_id})")

    try:
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "아래는 유튜브 영상의 청크별 요약 목록이야. "
                        "이 내용을 종합하여 영상 전체 제목, 전체 요약, 카테고리를 생성해. "
                        "이 요약은 노션 페이지에 게시될 예정이니 깔끔하고 읽기 쉽게 작성해. "
                        "또한 카테고리는 가급적 다음 11개 중 하나로 분류해: "
                        "[요리, 운동, 자동차, 공부, 게임, 동물, 메이크업, 맛집, 뉴스, 예능, 재테크]. "
                        "만약 위 11개 중 적합한 것이 없다면 가장 어울리는 새 카테고리 단어를 생성해."
                    ),
                },
                {"role": "user", "content": all_summaries},
            ],
            response_format=VideoOverview,
        )
        overview = response.choices[0].message.parsed
        if response.usage:
            logger.info(f"  [토큰 사용량] 개요 생성: {response.usage.total_tokens}")
        title = overview.title
        full_summary = overview.full_summary
        category = overview.category
    except Exception as e:
        logger.warning(f"  전체 개요 생성 실패: {e}")
        title = f"영상 {video_id}"
        full_summary = all_summaries[:200]
        category = "미분류"

    logger.info(f"[LangGraph: 개요 생성] 완료 — 제목: {title}, 카테고리: {category}")

    return {"title": title, "full_summary": full_summary, "category": category}


# ==========================================
# LangGraph 그래프 조립
# ==========================================
def build_intelligence_graph():
    """
    LangGraph 그래프 구성:
      summarize_each_chunk → embed_summaries → generate_overview → END
    """
    graph = StateGraph(IntelligenceState)

    # 노드 등록
    graph.add_node("summarize_each_chunk", summarize_each_chunk)
    graph.add_node("embed_summaries", embed_summaries_node)
    graph.add_node("generate_overview", generate_overview)

    # 엣지 연결 (순차)
    graph.add_edge(START, "summarize_each_chunk")
    graph.add_edge("summarize_each_chunk", "embed_summaries")
    graph.add_edge("embed_summaries", "generate_overview")
    graph.add_edge("generate_overview", END)

    return graph.compile()


# 그래프 싱글톤 (Celery 워커 시작 시 1회 빌드)
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
