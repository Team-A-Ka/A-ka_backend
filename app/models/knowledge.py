from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import User

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SourceEnum(str, enum.Enum):
    FILE = "FILE"
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"


class StatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("category.id"))

    source_type: Mapped[SourceEnum] = mapped_column(
        SQLEnum(SourceEnum, name="source_type_enum", native_enum=False, length=32),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[StatusEnum] = mapped_column(
        SQLEnum(StatusEnum, name="status_enum", native_enum=False, length=32),
        nullable=False,
        server_default=StatusEnum.PENDING.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    user: Mapped["User"] = relationship("User", back_populates="knowledges")
    category: Mapped["Category"] = relationship("Category", back_populates="knowledges")
    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="knowledge",
        cascade="all, delete-orphan",
    )
    youtube_metadata: Mapped[Optional["YoutubeMetadata"]] = relationship(
        "YoutubeMetadata",
        back_populates="knowledge",
        uselist=False,
        cascade="all, delete-orphan",
    )


class YoutubeMetadata(Base):
    __tablename__ = "youtube_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge.id"), unique=True
    )

    video_id: Mapped[str] = mapped_column(String(50))
    channel_name: Mapped[str] = mapped_column(String(100))
    duration: Mapped[int] = mapped_column(Integer)
    thumbnail_url: Mapped[str] = mapped_column(Text)

    knowledge: Mapped["Knowledge"] = relationship(
        "Knowledge", back_populates="youtube_metadata"
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    knowledge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge.id"))

    content: Mapped[str] = mapped_column(Text)
    start_timestamp: Mapped[float] = mapped_column(Float)
    chunk_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary_detail: Mapped[str] = mapped_column(Text)

    knowledge: Mapped["Knowledge"] = relationship(
        "Knowledge", back_populates="chunks"
    )
