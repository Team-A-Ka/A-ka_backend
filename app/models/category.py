from datetime import datetime
from typing import List, TYPE_CHECKING
from sqlalchemy import String, BigInteger, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

if TYPE_CHECKING:
    from .knowledge import Knowledge

class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    knowledges: Mapped[List["Knowledge"]] = relationship("Knowledge", back_populates="category")