import concurrent.futures
import functools
import logging
import uuid

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.llm import (
    base_message_text,
    get_chat_model_primary,
    get_llm,
    get_openai_sdk_client,
    openai_embedding_model_id,
)
from app.schemas.graph_state import IntelligenceState, VideoOverview

logger = logging.getLogger("aka.upload.step2")

openai_client = get_openai_sdk_client()
_chunk_summary_llm = get_llm()

_overview_chain = None
_MIN_FULL_SUMMARY_LENGTH = 250


def _get_overview_chain():
    global _overview_chain
    if _overview_chain is None:
        _overview_chain = get_chat_model_primary().with_structured_output(VideoOverview)
    return _overview_chain


def _build_chunk_context_block(metadata: dict | None) -> str:
    metadata = metadata or {}
    video_title = (
        metadata.get("video_title") or metadata.get("title") or ""
    ).strip()
    channel_name = (metadata.get("channel_name") or "").strip()

    if not video_title and not channel_name:
        return ""

    lines = ["[영상 컨텍스트]"]
    if video_title:
        lines.append(f"- 영상 제목: {video_title}")
    if channel_name:
        lines.append(f"- 채널명: {channel_name}")
    lines.append(
        "위 제목/채널명에 등장하는 인물·사건·기관이 본 영상의 화자 또는 주제일 "
        "가능성이 높다. 청크 본문에서 대명사·일반 명칭으로만 지칭되더라도, "
        "위 컨텍스트와 명확히 매칭될 때는 해당 실제 이름/직책으로 표기하라."
    )
    return "\n".join(lines)


def _build_legal_role_hint(metadata: dict | None, content: str) -> str:
    metadata = metadata or {}
    video_title = metadata.get("video_title") or metadata.get("title") or ""
    legal_role_markers = ("피고인", "변호인", "재판부", "공소장", "재판")
    if not any(marker in content for marker in legal_role_markers):
        return ""
    if not video_title:
        return ""

    return (
        "[법적 지위 힌트]\n"
        f"청크 본문에 재판/법적 지위 단서가 있고, 영상 제목은 '{video_title}'이다. "
        "본문의 '피고인' 같은 법적 지위는 생략하지 말고, 영상 제목의 핵심 인물명과 결합해 "
        "'피고인 [인물명]' 형태로 요약에 포함하라."
    )


_CHUNK_SYSTEM_PROMPT = (
    "너는 유튜브 영상 텍스트 조각을 요약하는 AI다. "
    "핵심 인사이트와 정보 중심으로 2~3문장으로 간결하게 한국어로 요약한다. "
    "불필요한 인트로, 인사, 광고 문구는 제외한다. "
    "자막 오류나 중복 표현은 의미를 유지하면서 자연스럽게 정리한다. "
    "예: '군사망 사망 사건'은 '군 사망 사건' 또는 '군내 사망 사건'으로 쓴다.\n\n"
    "[화자·인물 표기 규칙 — 반드시 따름]\n"
    "1. 다음 일반 명칭의 단독 사용을 금지한다: '피고인', '발언자', '화자', "
    "'그', '그녀', '이 사람', '한 인물', '관계자', '당사자'. "
    "원문에 이런 표현이 있어도 그대로 옮기지 말고, 가능한 한 실제 인명·직책·기관명과 결합한다. "
    "단, 법적 지위가 핵심 맥락이면 삭제하지 말고 '피고인 윤석열 전 대통령'처럼 이름과 함께 보존한다.\n"
    "2. 제공된 [영상 컨텍스트]의 영상 제목·채널명에 인물명/직책/사건명이 "
    "있다면 그것을 화자 또는 주제 인물로 우선 사용한다.\n"
    "3. 청크 본문에 '피고인', '변호인', '재판부', '공소장'처럼 재판 맥락 단서가 있고 "
    "영상 컨텍스트에 핵심 인물명이 있으면, 법적 지위와 인물명을 결합해 표기한다. "
    "예: '피고인이 발언했다'가 아니라 '피고인 윤석열 전 대통령이 발언했다'.\n"
    "4. 청크 본문 안에 인명·직책·기관명·사건명이 명시되어 있으면 익명화·일반화하지 말고 "
    "그 표현을 그대로 보존한다.\n"
    "5. 컨텍스트와 본문 모두 인물을 특정할 단서가 전혀 없는 경우에 한해, "
    "'화자' 등 중립적 명칭을 최소한으로 사용한다. 법적 지위는 근거가 있을 때만 이름과 함께 쓴다."
)


def _expand_full_summary_if_needed(
    *,
    title: str,
    full_summary: str,
    overview_input: str,
) -> str:
    if len((full_summary or "").strip()) >= _MIN_FULL_SUMMARY_LENGTH:
        return full_summary

    try:
        response = _chunk_summary_llm.invoke(
            [
                SystemMessage(
                    content=(
                        "너는 유튜브 영상 요약문을 상세하게 보강하는 AI다. "
                        "입력으로 제공된 영상 제목, 채널명, 청크별 요약, 초안 요약만 근거로 사용한다. "
                        "없는 사실을 추가하지 말고, 이미 있는 정보를 더 구체적이고 읽기 쉽게 확장한다. "
                        "결과는 한국어 문단 하나로 작성하고, 3~5문장, 250~450자 분량으로 작성한다. "
                        "사건 배경, 핵심 인물, 주요 주장, 근거, 쟁점을 압축해서 포함한다. "
                        "\n[법률/재판 영상 특화 규칙 — 해당 영상에만 적용]\n"
                        "재판 관련 영상이면 당사자의 법적 지위(피고인, 변호인, 증인 등)를 이름과 함께 포함한다. "
                        "초안이나 원본 정보에 '피고인 [이름]' 표현이 있으면 첫 문장에 반드시 보존한다.\n"
                        "[주의] 원본 정보가 재판·법원·검찰·혐의 맥락을 명시하지 않으면 "
                        "'피고인', '변호인', '증인' 같은 법정 용어를 절대 만들지 않는다. "
                        "일반 영상(음악, 브이로그, 강의, 일반 리뷰 등)에서는 절대 임의로 지어내어 추가하지 않는다."
                    ),
                ),
                HumanMessage(
                    content=(
                        f"요약 제목: {title}\n\n"
                        f"초안 요약:\n{full_summary}\n\n"
                        f"원본 정보:\n{overview_input}\n\n"
                        "위 정보만 바탕으로 full_summary에 들어갈 3~5문장 요약문을 다시 작성해줘."
                    )
                ),
            ]
        )
        expanded = base_message_text(response)
        if expanded:
            return expanded
    except Exception as exc:
        logger.warning(f"  summary expansion failed: {exc}")

    return full_summary


def _process_single_chunk(
    chunk,
    context_block: str = "",
    metadata: dict | None = None,
):
    content = chunk.get("content", "")
    user_message_parts = []
    if context_block:
        user_message_parts.append(context_block)
    legal_role_hint = _build_legal_role_hint(
        metadata,
        content,
    )
    if legal_role_hint:
        user_message_parts.append(legal_role_hint)
    user_message_parts.append("[청크 본문]\n" + content)
    user_message = "\n\n".join(user_message_parts)

    try:
        response = _chunk_summary_llm.invoke(
            [
                SystemMessage(content=_CHUNK_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ],
        )
        summary = base_message_text(response)
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            logger.debug(f"  chunk summary usage: {usage_meta}")
    except Exception as exc:
        logger.warning(f"  chunk {chunk.get('chunk_order', '?')} summary failed: {exc}")
        summary = chunk.get("content", "")[:100] + "..."

    logger.debug(f"  chunk {chunk.get('chunk_order', '?')} summary done")
    return {**chunk, "summary": summary}


def summarize_each_chunk(state: IntelligenceState) -> dict:
    video_id = state.get("video_id", "Unknown")
    chunks = state.get("chunks", [])
    metadata = state.get("metadata") or {}

    context_block = _build_chunk_context_block(metadata)

    logger.info(
        f"[LangGraph: chunk summary] start (video_id={video_id}, chunks={len(chunks)})"
    )
    # 완료 시점은 summarized_chunks 반환 후 info로 찍힘 (아래 return 이후 불가 → 호출자에서 처리)

    chunk_runner = functools.partial(
        _process_single_chunk, context_block=context_block, metadata=metadata
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(chunk_runner, chunks)
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
            model=openai_embedding_model_id(),
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        for index, chunk in enumerate(summarized_chunks):
            if index < len(embeddings):
                chunk["embedding"] = embeddings[index]
        if hasattr(response, "usage") and response.usage:
            logger.debug(f"  embedding tokens: {response.usage.total_tokens}")
        if embeddings:
            logger.info(
                f"  embeddings created: {len(embeddings)}, dim={len(embeddings[0])}"
            )
    except Exception as exc:
        logger.error(f"  embedding API failed: {exc}")

    return {"embeddings": embeddings}


def generate_overview(state: IntelligenceState) -> dict:
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])
    metadata = state.get("metadata") or {}
    video_title = metadata.get("video_title") or metadata.get("title") or "Unknown"
    channel_name = metadata.get("channel_name") or "Unknown"

    all_summaries = "\n".join(
        f"[{chunk.get('chunk_order', '?')}] {chunk.get('summary', '')}"
        for chunk in summarized_chunks
    )
    overview_input = (
        f"영상 제목: {video_title}\n"
        f"채널명: {channel_name}\n"
        f"영상 ID: {video_id}\n\n"
        f"청크별 요약:\n{all_summaries}"
    )

    logger.info(f"[LangGraph: overview] start (video_id={video_id})")

    try:
        overview = _get_overview_chain().invoke(
            [
                SystemMessage(
                    content=(
                        "아래는 유튜브 영상의 청크별 요약 목록이다. "
                        "영상 제목과 채널명을 함께 참고해 핵심 인물, 사건, 맥락을 보존한다. "
                        "내용을 종합해 새 요약 제목, 핵심 요약, 카테고리를 생성한다. "
                        "최종 요약에는 누가, 어떤 상황에서, 무엇을 주장하거나 설명했는지 포함한다.\n\n"
                        "[요약 제목 생성 규칙 — 반드시 따름]\n"
                        "- 콘텐츠 타입에 따라 다음 규칙을 적용한다:\n"
                        "  * 음악/노래 (자막이 가사 중심인 경우): 청크 요약(가사 내용)보다 제공된 '영상 제목'과 '채널명'을 최우선으로 참고하여, 곡명과 아티스트 중심으로 제목을 작성한다. (예: 원본 제목이 'aespa - Spicy'인 경우 곡명을 살려서 작성)\n"
                        "  * 일반 영상 (뉴스/강의/리뷰 등): 입력된 '영상 제목'은 참고만 하고 그대로 복사하지 않으며, 청크 요약의 핵심 내용을 바탕으로 새 정보형 제목을 만든다.\n"
                        "- '분노', '자폭', '충격', '무슨 일', '술렁이는', '놀란'처럼 클릭을 유도하는 감정적 표현은 제거한다.\n"
                        "- 일반 영상의 title은 핵심 인물 + 사건/쟁점 + 발언/주장을 드러내야 한다.\n"
                        "- 일반 영상 예: 원본 제목이 '분노한 윤석열, 분노 못참다 자폭...'이라도 "
                        "title은 '윤석열 군 사망사건 수사권 주장'처럼 작성한다.\n\n"
                        "[핵심 요약 작성 규칙 — 반드시 따름]\n"
                        "- 음악/노래 영상인 경우 가사를 시적으로 풀이하지 말고, 영상 제목과 채널명을 활용해 어떤 아티스트의 어떤 곡인지, 어떤 분위기인지 중심으로 간략히 요약한다.\n"
                        "- 일반 영상인 경우, full_summary는 제목을 길게 풀어쓴 수준이 아니라, 영상을 보지 않아도 핵심 흐름을 이해할 수 있는 요약이어야 한다.\n"
                        "- 반드시 3~5문장으로 작성하고, 가능하면 250~450자 분량으로 압축해서 작성한다.\n"
                        "- 사건 배경, 핵심 인물, 주요 발언/주장, 근거, 쟁점을 포함하되 불필요한 반복은 제거한다.\n"
                        "- 법률, 정치, 뉴스, 재판 관련 영상이면 관련 법/제도, 사건명, 쟁점, 책임 소재를 빠뜨리지 않는다.\n"
                        "- 원본 정보가 재판·법원·검찰·혐의 맥락을 명시하지 않으면 '피고인', '변호인', '증인' 같은 법정 용어를 만들지 않는다.\n"
                        "- 추상적인 표현만 반복하지 말고, 청크 요약에 나온 구체적 내용을 우선 반영한다.\n"
                        "- 단순히 '중요성을 강조했다', '논의가 이루어졌다'처럼 끝내지 말고 무엇을 왜 강조했는지 설명한다.\n"
                        "- 자막 오류나 중복 표현은 의미를 유지하면서 자연스럽게 정리한다. "
                        "예: '군사망 사망 사건'은 '군 사망 사건' 또는 '군내 사망 사건'으로 쓴다.\n"
                        "- 5문장을 넘기지 않는다.\n\n"
                        "[법률/재판 영상 특화 규칙 — 해당 영상에만 적용]\n"
                        "- 관련 법/제도, 사건명, 쟁점, 책임 소재를 빠뜨리지 않는다.\n"
                        "- 누가 피고인/변호인/증인인지, 어떤 사건이나 혐의 맥락에서 발언했는지 포함한다.\n"
                        "- 청크 요약에 '피고인 OOO'처럼 법적 지위와 이름이 명시된 경우, full_summary 첫 문장에 그 표현을 보존한다.\n"
                        "- [주의] 일반 영상(음악, 브이로그, 강의, 일반 리뷰 등)에서는 절대 '피고인', '변호인' 등의 단어를 임의로 지어내어 추가하지 않는다.\n\n"
                        "[화자·인물 표기 규칙 — 반드시 따름]\n"
                        "- 다음 일반 명칭의 단독 사용을 금지한다: '피고인', '발언자', '화자', "
                        "'그', '그녀', '이 사람', '한 인물', '관계자', '당사자'. "
                        "다만 법적 지위가 핵심 맥락이면 '피고인 윤석열 전 대통령'처럼 이름과 함께 쓴다.\n"
                        "- 영상 제목·채널명에 인물명/직책/사건명이 명시되어 있다면 "
                        "그것을 화자나 핵심 인물로 우선 표기한다.\n"
                        "- 청크 요약에 '피고인' 등 일반 명칭이 남아 있으면, 영상 제목/채널명과 "
                        "맥락을 종합해 '피고인 윤석열 전 대통령'처럼 실제 인명·직책을 붙여 최종 요약을 작성한다.\n"
                        "- 이미 청크 요약에 '피고인 [인물명]' 형태가 있다면, 최종 요약에서 법적 지위를 삭제하지 않는다.\n"
                        "- 단서가 전혀 없는 경우에 한해 '화자' 같은 중립 명칭을 최소한으로 쓴다. "
                        "법적 지위는 근거가 있을 때만 이름과 함께 쓴다.\n\n"
                        "요약은 Notion 페이지에 게시할 예정이므로 깔끔하고 읽기 쉽게 작성한다. "
                        "카테고리는 영상의 형식이 아니라 핵심 주제로 분류한다."
                    ),
                ),
                HumanMessage(content=overview_input),
            ],
        )
        if isinstance(overview, dict):
            overview = VideoOverview.model_validate(overview)
        title = overview.title
        full_summary = overview.full_summary
        category = overview.category
        full_summary = _expand_full_summary_if_needed(
            title=title,
            full_summary=full_summary,
            overview_input=overview_input,
        )
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
        run_id = str(uuid.uuid4())
        logger.info(
            f"LangGraph 시작 (video_id={data.get('video_id')}) | langsmith_run_id={run_id}"
        )

        result = intelligence_graph.invoke(
            {
                "video_id": data.get("video_id"),
                "chunks": data.get("chunks", []),
                "summarized_chunks": [],
                "embeddings": [],
                "title": "",
                "full_summary": "",
                "category": "",
                "metadata": data.get("metadata") or {},
            },
            config=RunnableConfig(run_id=run_id),
        )
        logger.info(
            f"LangGraph 완료 (video_id={data.get('video_id')}) | langsmith_run_id={run_id}"
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
