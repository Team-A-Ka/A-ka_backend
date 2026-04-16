# SQLAlchemy 메타데이터에 모델 등록 (Alembic / create_all 용)
from database import Base

from app.models.user import User, UserInterest
from app.models.category import Category
from app.models.knowledge import (
    Knowledge,
    KnowledgeChunk,
    SourceEnum,
    StatusEnum,
    YoutubeMetadata,
)

__all__ = [
    "Base",
    "User",
    "UserInterest",
    "Category",
    "Knowledge",
    "YoutubeMetadata",
    "KnowledgeChunk",
    "SourceEnum",
    "StatusEnum",
]
