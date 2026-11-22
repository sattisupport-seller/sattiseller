"""ADR-0005 / пункт 1.15: общие лимиты частоты в базе данных (таблица rate_limits)

Revision ID: g3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-20 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'g3a4b5c6d7e8'
down_revision: str | None = 'f2a3b4c5d6e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'rate_limits',
        sa.Column('key', sa.String(length=160), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('rate_limits')
