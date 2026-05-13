"""rename constraints to naming_convention

naming_convention 도입 전 PostgreSQL이 자동 부여한 제약 이름을
convention 규칙(uq_<table>_<column>)에 맞게 일괄 변경.

대상:
  category_name_key             → uq_category_name
  user_user_name_key            → uq_user_user_name
  youtube_metadata_knowledge_id_key → uq_youtube_metadata_knowledge_id

Revision ID: 202605130002
Revises: 202605130001
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "202605130002"
down_revision: Union[str, Sequence[str], None] = "202605130001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE category RENAME CONSTRAINT category_name_key TO uq_category_name")
    op.execute("ALTER TABLE \"user\" RENAME CONSTRAINT user_user_name_key TO uq_user_user_name")
    op.execute("ALTER TABLE youtube_metadata RENAME CONSTRAINT youtube_metadata_knowledge_id_key TO uq_youtube_metadata_knowledge_id")


def downgrade() -> None:
    op.execute("ALTER TABLE youtube_metadata RENAME CONSTRAINT uq_youtube_metadata_knowledge_id TO youtube_metadata_knowledge_id_key")
    op.execute("ALTER TABLE \"user\" RENAME CONSTRAINT uq_user_user_name TO user_user_name_key")
    op.execute("ALTER TABLE category RENAME CONSTRAINT uq_category_name TO category_name_key")
