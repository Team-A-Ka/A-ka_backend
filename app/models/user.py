from datetime import datetime
from typing import List, TYPE_CHECKING
from sqlalchemy import String, BigInteger, TIMESTAMP, func, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

if TYPE_CHECKING:
    from .knowledge import Knowledge

class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_name: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)     #로그인 할 때의 id와 같은 개념(사용자 이름 X)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    knowledges: Mapped[List["Knowledge"]] = relationship("Knowledge", back_populates="user")
    channel_identities: Mapped[List["UserChannelIdentity"]] = relationship(
        "UserChannelIdentity", back_populates="user", cascade="all, delete-orphan"
    )

class UserChannelIdentity(Base):
    __tablename__ = "user_channel_identity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="channel_identities")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
    )