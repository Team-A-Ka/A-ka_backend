from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.models.knowledge import Knowledge

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Category(Base):
    __tablename__ = "category"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    knowledges: Mapped[List["Knowledge"]] = relationship(
        "Knowledge", back_populates="category"
    )
