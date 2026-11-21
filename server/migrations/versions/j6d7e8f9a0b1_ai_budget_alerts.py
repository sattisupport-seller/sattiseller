"""1.4: оповещения владельцу о бюджете ИИ (один раз на уровень в месяц)

Revision ID: j6d7e8f9a0b1
Revises: i5c6d7e8f9a0
Create Date: 2026-11-21 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'j6d7e8f9a0b1'
down_revision: str | None = 'i5c6d7e8f9a0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'ai_budget_alerts',
        sa.Column('month', sa.String(length=7), primary_key=True),
        sa.Column('level', sa.String(length=16), primary_key=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('ai_budget_alerts')
