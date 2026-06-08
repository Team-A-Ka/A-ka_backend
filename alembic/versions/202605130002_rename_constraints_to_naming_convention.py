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


def _rename_constraint_if_exists(table_sql: str, regclass_sql: str, old: str, new: str) -> None:
    """레거시 DB(옛 자동생성 제약명)에서만 rename한다.
    squashed_baseline(202605130001)로 만든 새 DB는 이미 convention 이름이라
    old 제약이 없으므로 no-op → clean `alembic upgrade head`가 통과한다."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{old}' AND conrelid = '{regclass_sql}'::regclass
            ) THEN
                ALTER TABLE {table_sql} RENAME CONSTRAINT {old} TO {new};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _rename_constraint_if_exists("category", "category", "category_name_key", "uq_category_name")
    _rename_constraint_if_exists('"user"', '"user"', "user_user_name_key", "uq_user_user_name")
    _rename_constraint_if_exists(
        "youtube_metadata", "youtube_metadata",
        "youtube_metadata_knowledge_id_key", "uq_youtube_metadata_knowledge_id",
    )


def downgrade() -> None:
    _rename_constraint_if_exists(
        "youtube_metadata", "youtube_metadata",
        "uq_youtube_metadata_knowledge_id", "youtube_metadata_knowledge_id_key",
    )
    _rename_constraint_if_exists('"user"', '"user"', "uq_user_user_name", "user_user_name_key")
    _rename_constraint_if_exists("category", "category", "uq_category_name", "category_name_key")
