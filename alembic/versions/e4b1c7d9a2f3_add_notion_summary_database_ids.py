"""add notion summary database ids

Revision ID: e4b1c7d9a2f3
Revises: d2f4c8a9b1e7, 8f7cfbed1a19
Create Date: 2026-05-11 16:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4b1c7d9a2f3"
down_revision: Union[str, Sequence[str], None] = (
    "d2f4c8a9b1e7",
    "8f7cfbed1a19",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notion_connection",
        sa.Column("summary_database_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "notion_connection",
        sa.Column("summary_data_source_id", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notion_connection", "summary_data_source_id")
    op.drop_column("notion_connection", "summary_database_id")
