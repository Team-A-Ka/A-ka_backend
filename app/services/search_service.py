"""
[SEARCH 파이프라인 — LangGraph 기반 RAG 답변 생성]

LangGraph 흐름:
  [vectorize_query] → [search_chunks] → (결과 있음?) → [generate_answer] → END
                                          (없음?)     → [no_result_reply] → END

호출 위치: router_service.py → intent == "SEARCH" 분기
"""

import logging
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from app.core.config import settings
from app.schemas.graph_state import SearchState

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


# ==========================================
# LangGraph 노드 1: 질문 벡터화
# ==========================================
def vectorize_query(state: SearchState) -> dict:
    """사용자 질문을 1536차원 벡터로 변환"""
    query = state.get("query", "")
    logger.info(f"[SEARCH 노드1: 벡터화] 시작")

    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    query_vector = response.data[0].embedding
    if hasattr(response, "usage") and response.usage:
        logger.info(f"  [토큰 사용량] 벡터화: {response.usage.total_tokens}")

    logger.info(f"[SEARCH 노드1: 벡터화] 완료 (차원: {len(query_vector)})")
    return {"query_vector": query_vector}


# ==========================================
# LangGraph 노드 2: pgvector 유사도 검색
# ==========================================
def search_chunks(state: SearchState) -> dict:
    """pgvector에서 유사도 높은 청크 검색"""
    query_vector = state.get("query_vector", [])
    user_id = state.get("user_id", "")

    logger.info(f"[SEARCH 노드2: 검색] 시작")

    # ── 수정 포인트 (유리) ──
    # 유리님이 embedding 컬럼을 추가한 후 아래 실제 쿼리로 교체
    # session = SessionLocal()
    # try:
    #     vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
    #     result = session.execute(
    #         text("""
    #             SELECT kc.content, kc.summary_detail, k.title, k.original_url,
    #                    kc.embedding <=> :query_vec AS distance
    #             FROM youtube_knowledge_chunk kc
    #             JOIN knowledge k ON kc.knowledge_id = k.id
    #             WHERE k.user_id = :user_id
    #               AND kc.embedding IS NOT NULL
    #             ORDER BY kc.embedding <=> :query_vec
    #             LIMIT 5
    #         """),
    #         {"query_vec": vector_str, "user_id": user_id}
    #     )
    #     chunks = [dict(row._mapping) for row in result]
    # finally:
    #     session.close()

    # 더미 결과 (pgvector 세팅 전까지 사용)
    logger.warning("[SEARCH 노드2] pgvector 미구성 — 더미 검색 결과 반환")
    chunks = []

    logger.info(f"[SEARCH 노드2: 검색] 완료 — {len(chunks)}개 청크 발견")
    return {"chunks": chunks, "sources": len(chunks)}


# ==========================================
# LangGraph 노드 3a: RAG 답변 생성 (검색 결과 있을 때)
# ==========================================
def generate_answer(state: SearchState) -> dict:
    """검색된 청크를 context로 넣어 OpenAI에 답변 생성"""
    query = state.get("query", "")
    chunks = state.get("chunks", [])

    logger.info(f"[SEARCH 노드3: RAG 답변] 시작 (context: {len(chunks)}개 청크)")

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("title", "알 수 없는 영상")
        content = chunk.get("summary_detail") or chunk.get("content", "")
        context_parts.append(f"[출처 {i}: {title}]\n{content}")

    context_text = "\n\n".join(context_parts)

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 사용자가 저장한 유튜브 영상 내용을 기반으로 답변하는 AI 어시스턴트야. "
                        "아래 [검색 결과]는 사용자가 이전에 저장한 영상의 관련 내용이야. "
                        "이 내용을 근거로 질문에 답변해. "
                        "검색 결과에 없는 내용은 추측하지 말고 '저장된 영상에서는 해당 내용을 찾지 못했어요'라고 답해. "
                        "답변은 친절하고 간결하게 3~5문장으로 해."
                    ),
                },
                {
                    "role": "user",
                    "content": f"[검색 결과]\n{context_text}\n\n[질문]\n{query}",
                },
            ],
        )
        answer = response.choices[0].message.content.strip()
        if response.usage:
            logger.info(f"  [토큰 사용량] RAG 답변: {response.usage.total_tokens}")
    except Exception as e:
        logger.error(f"RAG 답변 생성 실패: {e}")
        answer = "답변 생성 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."

    logger.info(f"[SEARCH 노드3: RAG 답변] 완료")
    return {"answer": answer}


# ==========================================
# LangGraph 노드 3b: 안내 메시지 (검색 결과 없을 때)
# ==========================================
def no_result_reply(state: SearchState) -> dict:
    """저장된 데이터가 없을 때 안내 메시지"""
    logger.info(f"[SEARCH 노드3: 안내] 검색 결과 없음")
    return {
        "answer": "아직 저장된 영상 데이터가 없어서 검색 결과가 없어요. 먼저 영상 링크를 보내주세요!"
    }


# ==========================================
# 조건 분기: 검색 결과 유무 판단
# ==========================================
def has_results(state: SearchState) -> str:
    """검색 결과가 있으면 generate_answer, 없으면 no_result_reply"""
    if state["chunks"]:
        return "generate_answer"
    return "no_result_reply"


# ==========================================
# LangGraph 그래프 조립
# ==========================================
def build_search_graph():
    """
    SEARCH 그래프:
      vectorize_query → search_chunks → (결과?) → generate_answer → END
                                          └────→ no_result_reply → END
    """
    graph = StateGraph(SearchState)

    graph.add_node("vectorize_query", vectorize_query)
    graph.add_node("search_chunks", search_chunks)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("no_result_reply", no_result_reply)

    graph.add_edge(START, "vectorize_query")
    graph.add_edge("vectorize_query", "search_chunks")
    graph.add_conditional_edges("search_chunks", has_results)
    graph.add_edge("generate_answer", END)
    graph.add_edge("no_result_reply", END)

    return graph.compile()


# 그래프 싱글톤
search_graph = build_search_graph()


# ==========================================
# 단일 진입점 — router_service.py에서 호출
# ==========================================
def search_and_answer(user_id: str, query: str) -> dict:
    """SEARCH 파이프라인 실행"""
    logger.info(f"[SEARCH] 시작 (user: {user_id}, query: {query[:30]}...)")

    result = search_graph.invoke(
        {
            "user_id": user_id,
            "query": query,
            "query_vector": [],
            "chunks": [],
            "answer": "",
            "sources": 0,
        }
    )

    logger.info(f"[SEARCH] 완료 — 답변 생성됨 (출처: {result['sources']}개)")

    return {
        "answer": result["answer"],
        "sources": result["sources"],
    }
