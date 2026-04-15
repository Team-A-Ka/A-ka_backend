from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4
from sqlmodel import Field, Relationship, SQLModel, Enum


# 공통 소스 타입 및 상태 관리
class SourceType(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class ProcessStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Knowledge(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id")
    category_id: UUID = Field(foreign_key="category.id")
    source_type: SourceType
    title: str = Field(max_length=255)
    original_url: str
    status: ProcessStatus = Field(default=ProcessStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary: Optional[str] = None
    hit_count: int = Field(default=0)


class YoutubeMetadata(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    knowledge_id: UUID = Field(foreign_key="knowledge.id", unique=True)
    video_id: str = Field(max_length=50)
    channel_name: str = Field(max_length=100)
    duration: int
    thumbnail_url: str


class KnowledgeChunk(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    knowledge_id: UUID = Field(foreign_key="knowledge.id")
    content: str
    start_timestamp: float
    chunk_order: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary_detail: str
