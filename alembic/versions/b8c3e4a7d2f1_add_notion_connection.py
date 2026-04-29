"""add notion connection

Revision ID: b8c3e4a7d2f1
Revises: fa51fd3fd00c
Create Date: 2026-04-28 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8c3e4a7d2f1"
down_revision: Union[str, Sequence[str], None] = "fa51fd3fd00c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notion_connection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.String(length=100), nullable=False),
        sa.Column("workspace_name", sa.String(length=255), nullable=True),
        sa.Column("workspace_icon", sa.String(length=1000), nullable=True),
        sa.Column("bot_id", sa.String(length=100), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("parent_page_id", sa.String(length=50), nullable=True),
        sa.Column("duplicated_template_id", sa.String(length=50), nullable=True),
        sa.Column("owner_type", sa.String(length=50), nullable=True),
        sa.Column("owner_user_id", sa.String(length=100), nullable=True),
        sa.Column("owner_user_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_notion_connection_user_id"),
    )
    op.create_index(
        op.f("ix_notion_connection_user_id"),
        "notion_connection",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_notion_connection_user_id"), table_name="notion_connection")
    op.drop_table("notion_connection")
