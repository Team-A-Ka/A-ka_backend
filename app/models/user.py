from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import BigInteger, Column
from .knowledge import Knowledge

class User(SQLModel, table=True):
    id: Optional[int] = Field(
        default=None, 
        primary_key=True, 
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    ) 
    user_name: str = Field(max_length=50)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    knowledges: List["Knowledge"] = Relationship(back_populates="user")