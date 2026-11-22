"""3.9: счётчики событий аналитики по дням (без персональных данных)

Revision ID: k7e8f9a0b1c2
Revises: j6d7e8f9a0b1
Create Date: 2026-11-21 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'k7e8f9a0b1c2'
down_revision: str | None = 'j6d7e8f9a0b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'analytics_daily',
        sa.Column('day', sa.String(length=10), primary_key=True),
        sa.Column('event', sa.String(length=64), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('analytics_daily')
