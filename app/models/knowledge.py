from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, BigInteger, ForeignKey, Text, TIMESTAMP, func, Enum as SQL_Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid
from database import Base
import enum

class SourceType(enum.Enum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    FILE = "FILE"

class ProcessStatus(enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

if TYPE_CHECKING:
    from .user import User
    from .category import Category

class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("category.id"), nullable=True)
    source_type: Mapped[SourceType] = mapped_column(SQL_Enum(SourceType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_url: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProcessStatus] = mapped_column(SQL_Enum(ProcessStatus), default=ProcessStatus.PENDING)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hit_count: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="knowledges")
    category: Mapped[Optional["Category"]] = relationship("Category", back_populates="knowledges")
    youtube_metadata: Mapped["YoutubeMetadata"] = relationship("YoutubeMetadata", back_populates="knowledge", uselist=False)
    chunks: Mapped[List["YoutubeKnowledgeChunk"]] = relationship("YoutubeKnowledgeChunk", back_populates="knowledge")

class YoutubeMetadata(Base):
    __tablename__ = "youtube_metadata"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge.id"), unique=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String(50), nullable=False)
    video_title: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(50), nullable=False)
    duration: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    knowledge: Mapped["Knowledge"] = relationship("Knowledge", back_populates="youtube_metadata")

class YoutubeKnowledgeChunk(Base):
    __tablename__ = "youtube_knowledge_chunk"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_order: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    knowledge: Mapped["Knowledge"] = relationship("Knowledge", back_populates="chunks")