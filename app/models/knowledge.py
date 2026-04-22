from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import BigInteger, Column, Text, String
from enum import Enum
from .category import Category  

class SourceType(str, Enum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    FILE = "FILE"

class ProcessStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Knowledge(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(sa_column=Column(BigInteger, index=True))
    category_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, index=True))
    source_type: SourceType
    title: str = Field(max_length=255)
    original_url: str = Field(max_length=255)
    status: ProcessStatus = Field(default=ProcessStatus.PENDING)
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    hit_count: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )


    category: Optional["Category"] = Relationship(back_populates="knowledges")
    youtube_metadata: Optional["YoutubeMetadata"] = Relationship(back_populates="knowledge")
    chunks: List["YoutubeKnowledgeChunk"] = Relationship(back_populates="knowledge")


class YoutubeMetadata(SQLModel, table=True):
    __tablename__ = "youtube_metadata"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    knowledge_id: UUID = Field(foreign_key="knowledge.id", unique=True, index=True)
    video_id: str = Field(max_length=50)
    video_title: str = Field(max_length=255)
    channel_name: str = Field(max_length=50)
    duration: int = Field(sa_column=Column(BigInteger)) 
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    knowledge: Optional[Knowledge] = Relationship(back_populates="youtube_metadata")

class YoutubeKnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunk"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    knowledge_id: UUID = Field(foreign_key="knowledge.id", index=True)
    content: str = Field(sa_column=Column(Text))
    summary_detail: Optional[str] = Field(default=None, sa_column=Column(Text))
    start_time: int = Field(sa_column=Column(BigInteger)) 
    chunk_order: int = Field()
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    knowledge: Optional[Knowledge] = Relationship(back_populates="chunks")