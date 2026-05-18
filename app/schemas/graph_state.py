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
    metadata: dict            # Step 1 — 영상 제목/채널명 등 메타데이터
    chunks: list              # Step 1 — 자막 추출+청킹 결과 (collect_and_chunk)
    summarized_chunks: list   # Step 2 노드1 — 청크별 요약 (summarize_each_chunk)
    embeddings: list          # Step 2 노드2 — 요약문 벡터화 (embed_summaries_node)
    title: str                # Step 2 노드3 — 영상 제목 (generate_overview)
    full_summary: str         # Step 2 노드3 — 전체 개요, 노션 업로드용 (generate_overview)
    category: str             # Step 2 노드3 — AI 판별 카테고리, 15개 우산 중 1 또는 새 우산 (generate_overview)


# ==========================================
# SEARCH 파이프라인용 State
# ==========================================
class SearchState(TypedDict):
    """SEARCH 파이프라인 — LangGraph 노드 간 공유 상태"""
    user_id: int
    query: str                # 사용자 질문 원문
    query_vector: list        # 질문 벡터 (1536차원)
    chunks: list              # pgvector 검색 결과
    answer: str               # RAG 생성 답변
    sources: int              # 검색된 청크 수


# ==========================================
# 기본 카테고리 후보 (LangGraph가 우선 선택)
# ==========================================
# 우산(umbrella) 우선 — 좁은 새 카테고리를 만들기보다 이 후보 중 하나의 우산에
# 합류시키는 것을 기본 동작으로 한다. 유사 주제가 분산되지 않게 하기 위함.
DEFAULT_CATEGORIES = [
    "요리", "운동", "자동차", "공부", "게임",
    "동물", "메이크업", "맛집", "뉴스", "예능", "재테크",
    # 추가 우산 — 자주 등장하지만 기존 11개에 안 잡히던 영역
    "과학",       # 화학·물리·생물·뇌과학·천문·기후 등 자연과학 일반
    "사회문제",   # 군사·정치·범죄·시사·사건사고 등 사회 이슈
    "음악",       # 노래·MV·커버·작곡·악기·콘서트 등
    "프로그래밍", # 파이썬·C·백엔드·API·프레임워크·CS 등
]


# ==========================================
# OpenAI Structured Output 스키마
# ==========================================
class VideoOverview(BaseModel):
    """전체 개요 생성 시 OpenAI가 반환해야 하는 구조"""
    title: str = Field(
        description=(
            "원본 영상 제목을 그대로 복사하지 않고, 영상의 핵심 인물과 쟁점을 "
            "내용 중심으로 요약한 새 제목 (25자 이내)"
        )
    )
    full_summary: str = Field(
        description=(
            "영상을 보지 않아도 핵심 흐름을 이해할 수 있도록 사건 배경, "
            "주요 주장, 근거, 쟁점을 압축해 담은 3~5문장의 핵심 요약. "
            "재판 관련 영상이면 피고인 등 법적 지위를 이름과 함께 포함"
        )
    )
    category: str = Field(
        description=(
            "영상의 카테고리. 가능한 한 다음 15개 우산 카테고리 중 하나에 합류시킨다: "
            "요리, 운동, 자동차, 공부, 게임, 동물, 메이크업, 맛집, 뉴스, 예능, 재테크, "
            "과학, 사회문제, 음악, 프로그래밍. "
            "우산 우선 원칙: 좁은 새 카테고리를 만들기보다 위 우산 중 하나에 합류시키는 것이 기본 동작이다. "
            "유사 주제가 여러 좁은 이름으로 분산되면 검색·재조회 품질이 떨어진다. "
            "예: 화학·물리·생물·뇌과학·천문은 모두 '과학'. "
            "군사·정치·범죄·시사·사건사고는 모두 '사회문제'. "
            "헬스·요가·필라테스·스포츠는 모두 '운동'. "
            "파이썬·C·백엔드·API·프레임워크는 모두 '프로그래밍'. "
            "위 15개 우산 어느 것에도 합리적으로 들어가지 않는 경우에만 새 카테고리를 만든다. "
            "새 카테고리를 만들 때도 1~5자의 간결한 명사 + 충분히 넓은 우산이 되도록 한다 "
            "(좋은 예: '음악', '여행', '영화'. 나쁜 예: '발라드', '제주여행', 'SF영화')."
        )
    )
