"""merge migration heads

Revision ID: 8f7cfbed1a19
Revises: 45c4ac899d96, b8c3e4a7d2f1
Create Date: 2026-05-11 13:13:35.040161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f7cfbed1a19'
down_revision: Union[str, Sequence[str], None] = ('45c4ac899d96', 'b8c3e4a7d2f1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
