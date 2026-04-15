from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4
from sqlmodel import Field, Relationship, SQLModel, Enum


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_name: str = Field(max_length=100)
    user_context: Optional[dict] = Field(
        default=None, sa_column_kwargs={"type": "jsonb"}
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)
