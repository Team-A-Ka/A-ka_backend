from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, TIMESTAMP, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from .user import User


class NotionConnection(Base):
    __tablename__ = "notion_connection"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workspace_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_icon: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_page_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duplicated_template_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="notion_connection")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_notion_connection_user_id"),
    )
