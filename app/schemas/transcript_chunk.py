from enum import Enum

from pydantic import BaseModel, Field


class ChunkStrategy(str, Enum):
    """
    [자막 청킹 방식]
    시간 기반 / 글자수 기반 / 문장·유사도 기반
    """
    time = "time"
    char = "char"
    semantic = "semantic"


class TranscriptChunkResponse(BaseModel):
    """청킹 API 응답 - 구간 시작 시각(ms) + 본문."""
    start_time: int = Field(..., description="청크 시작 시각(ms). DB bigint와 호환되는 정수.")
    content: str = Field(..., description="해당 구간에 합쳐진 자막 본문.")


class TranscriptChunkParams(BaseModel):
    """청킹 요청: ``video_id``로 ``get_transcript``와 동일 경로에서 자막을 가져온 뒤 정제·청킹한다."""

    video_id: str = Field(..., description="YouTube 동영상 ID (자막은 get_transcript와 동일하게 조회)")
    language: str = Field("ko", description="자막 언어 코드")
    time_window_ms: int = Field(30_000, ge=500, description="시간 청킹: 윈도우 길이(ms)")
    max_chars: int = Field(500, ge=50, description="글자수 청킹: 청크 최대 글자 수")
    overlap_chars: int = Field(0, ge=0, description="글자수 청킹: 겹침 글자 수")
    semantic_threshold: float = Field(
        0.35,
        ge=0.0,
        le=1.0,
        description=(
            "시멘틱 청킹: 이웃 ‘문장 유닛’과의 단어-백 코사인 유사도가 이 값보다 작으면 청크를 끊음. "
            "유닛은 문장 부호·한국어 종결(습니다/니다/다/요 등) 경계에서만 나뉨. "
            "낮추면 더 잘 붙임, 높이면 더 자주 나눔."
        ),
    )
    semantic_min_paragraph_chars: int = Field(
        150,
        ge=30,
        description=(
            "시멘틱 전처리: 이 길이(글자 수) 미만인 문장 유닛은 다음 문장과 하나의 유닛으로 합침 "
            "(짧게 잘린 자막 조각을 흡수). 값을 키우면 유닛 수가 줄어듦."
        ),
    )
    semantic_min_chunk_chars: int = Field(
        0,
        ge=0,
        description=(
            "시멘틱 후처리: 유사도로 나뉜 **최종 청크**의 ``content`` 글자 수가 이 값 미만이면 다음 청크와 합침. "
            "0이면 비활성(기존 동작). 짧은 청크만 줄이고 싶을 때 사용."
        ),
    )


class TranscriptChunkRequest(TranscriptChunkParams):
    """단일 전략 청킹 요청: ``TranscriptChunkParams`` + ``strategy``."""

    strategy: ChunkStrategy
