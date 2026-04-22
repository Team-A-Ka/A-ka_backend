from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import BigInteger, Column
from .knowledge import Knowledge

class Category(SQLModel, table=True):
    id: Optional[int] = Field(
        default=None, 
        primary_key=True, 
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    ) # DB가 ID를 자동 생성하도록 허용하기 위해 Optional 설정

    name: str = Field(max_length=50, unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    knowledges: List["Knowledge"] = Relationship(back_populates="category")
