"""
LangGraph용 State 및 OpenAI Structured Output 스키마 정의

- IntelligenceState: UPLOAD 파이프라인의 LangGraph 노드 간 공유 상태
- SearchState: SEARCH 파이프라인의 LangGraph 노드 간 공유 상태
- VideoOverview: 전체 개요 생성 시 OpenAI가 반환해야 하는 구조
"""
from typing import TypedDict
from pydantic import BaseModel, Field


# ==========================================
# UPLOAD 파이프라인용 State
# ==========================================
class IntelligenceState(TypedDict):
    """UPLOAD 파이프라인 — LangGraph 노드 간 공유 상태"""
    video_id: str             # Step 1 (입력) — 라우터에서 추출한 영상 ID
    chunks: list              # Step 1 — 자막 추출+청킹 결과 (collect_and_chunk)
    summarized_chunks: list   # Step 2 노드1 — 청크별 요약 (summarize_each_chunk)
    embeddings: list          # Step 2 노드2 — 요약문 벡터화 (embed_summaries_node)
    title: str                # Step 2 노드3 — 영상 제목 (generate_overview)
    full_summary: str         # Step 2 노드3 — 전체 개요, 노션 업로드용 (generate_overview)
    category: str             # Step 2 노드3 — AI 판별 카테고리, 11개 중 1 (generate_overview)


# ==========================================
# SEARCH 파이프라인용 State
# ==========================================
class SearchState(TypedDict):
    """SEARCH 파이프라인 — LangGraph 노드 간 공유 상태"""
    user_id: str
    query: str                # 사용자 질문 원문
    query_vector: list        # 질문 벡터 (1536차원)
    chunks: list              # pgvector 검색 결과
    answer: str               # RAG 생성 답변
    sources: int              # 검색된 청크 수


# ==========================================
# 기본 카테고리 후보 (LangGraph가 우선 선택)
# ==========================================
DEFAULT_CATEGORIES = [
    "요리", "운동", "자동차", "공부", "게임",
    "동물", "메이크업", "맛집", "뉴스", "예능", "재테크",
]


# ==========================================
# OpenAI Structured Output 스키마
# ==========================================
class VideoOverview(BaseModel):
    """전체 개요 생성 시 OpenAI가 반환해야 하는 구조"""
    title: str = Field(description="영상의 핵심 주제를 나타내는 제목 (15자 이내)")
    full_summary: str = Field(description="영상 전체 내용을 3~5문장으로 요약")
    category: str = Field(
        description=(
            "영상의 카테고리. 가능하면 다음 11개 중 하나로 분류할 것: "
            "요리, 운동, 자동차, 공부, 게임, 동물, 메이크업, 맛집, 뉴스, 예능, 재테크. "
            "영상 내용이 이 11개 중 어디에도 명확히 속하지 않으면 "
            "가장 적합한 새 카테고리 이름을 자유롭게 생성할 것. "
            "새로 생성하는 경우에도 1~5자의 간결한 한 단어로 작성할 것."
        )
    )
# 카테고리 디폴트 11개 정한 것 보다 카테고리 테이블의 데이터를 조회해서 11개 제한 없이 ai가 생성한것들도 계속 사용가능하게.