"""prevent duplicate Notion owner connections

Revision ID: d2f4c8a9b1e7
Revises: b8c3e4a7d2f1, 45c4ac899d96
Create Date: 2026-05-07 14:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2f4c8a9b1e7"
down_revision: Union[str, Sequence[str], None] = (
    "b8c3e4a7d2f1",
    "45c4ac899d96",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OWNER_USER_INDEX = "uq_notion_connection_workspace_owner_user_id"
OWNER_EMAIL_INDEX = "uq_notion_connection_workspace_owner_email_without_user_id"


def upgrade() -> None:
    """Upgrade schema."""
    _raise_if_duplicate_notion_owners_exist()

    op.create_index(
        OWNER_USER_INDEX,
        "notion_connection",
        ["workspace_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index(
        OWNER_EMAIL_INDEX,
        "notion_connection",
        ["workspace_id", sa.text("lower(owner_user_email)")],
        unique=True,
        postgresql_where=sa.text(
            "owner_user_id IS NULL AND owner_user_email IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(OWNER_EMAIL_INDEX, table_name="notion_connection")
    op.drop_index(OWNER_USER_INDEX, table_name="notion_connection")


def _raise_if_duplicate_notion_owners_exist() -> None:
    bind = op.get_bind()

    owner_user_duplicates = bind.execute(
        sa.text(
            """
            SELECT workspace_id, owner_user_id, array_agg(user_id ORDER BY user_id) AS user_ids
            FROM notion_connection
            WHERE owner_user_id IS NOT NULL
            GROUP BY workspace_id, owner_user_id
            HAVING count(*) > 1
            """
        )
    ).fetchall()

    owner_email_duplicates = bind.execute(
        sa.text(
            """
            SELECT workspace_id, lower(owner_user_email) AS owner_email,
                   array_agg(user_id ORDER BY user_id) AS user_ids
            FROM notion_connection
            WHERE owner_user_id IS NULL AND owner_user_email IS NOT NULL
            GROUP BY workspace_id, lower(owner_user_email)
            HAVING count(*) > 1
            """
        )
    ).fetchall()

    if owner_user_duplicates or owner_email_duplicates:
        details = {
            "owner_user_id_duplicates": [dict(row._mapping) for row in owner_user_duplicates],
            "owner_email_duplicates": [dict(row._mapping) for row in owner_email_duplicates],
        }
        raise RuntimeError(
            "Duplicate Notion owner connections exist. "
            "Remove or merge duplicate notion_connection rows before applying "
            f"this migration: {details}"
        )
