"""3.8 (бета): оценка ответа помощника сохраняет вопрос с маскировкой и признак отказа

Revision ID: n1a2b3c4d5e6
Revises: m9a0b1c2d3e4
Create Date: 2026-11-22 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'n1a2b3c4d5e6'
down_revision: str | None = 'm9a0b1c2d3e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('ai_feedback') as batch:
        batch.add_column(sa.Column('question_masked', sa.Text(), nullable=True))
        batch.add_column(sa.Column('refused', sa.Boolean(), nullable=True))
        batch.add_column(sa.Column('refusal_category', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_feedback') as batch:
        batch.drop_column('refusal_category')
        batch.drop_column('refused')
        batch.drop_column('question_masked')
