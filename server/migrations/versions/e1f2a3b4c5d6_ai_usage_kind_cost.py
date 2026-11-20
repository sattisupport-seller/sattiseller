"""QA-03/QA-04: события ИИ хранят вид (вопрос или черновик) и стоимость вызова

Revision ID: e1f2a3b4c5d6
Revises: d9e2a3b4c5d6
Create Date: 2026-11-20 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e1f2a3b4c5d6'
down_revision: str | None = 'd9e2a3b4c5d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('ai_usage_events') as batch:
        batch.add_column(sa.Column('kind', sa.String(length=16), nullable=False, server_default='question'))
        batch.add_column(sa.Column('cost_micro_usd', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('ai_usage_events') as batch:
        batch.drop_column('cost_micro_usd')
        batch.drop_column('kind')
