from enum import Enum
from pydantic import BaseModel, Field


# 의도 분류 상수 Enum
class IntentType(str, Enum):
    SAVE_ONLY = "SAVE_ONLY"  # 단순 링크 저장
    UPLOAD = "UPLOAD"  # 링크 저장, 영상 요약 및 적재 등
    SEARCH = "SEARCH"  # 과거 데이터 기반 질문, 검색, RAG
    UNKNOWN = "UNKNOWN"  # 기타 일상 대화, 의미 없는 텍스트


# OpenAI Structured Output을 위한 Pydantic Schema
class IntentExtraction(BaseModel):
    intent: IntentType = Field(description="사용자 발화의 핵심 의도")
    detected_url: str | None = Field(
        description="사용자 발화에 포함된 URL. 없으면 null"
    )
