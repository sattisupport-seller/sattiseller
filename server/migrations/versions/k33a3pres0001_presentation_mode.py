"""Режим презентации (К-33, А3): флаг магазина и пометка «пример» у остатков.

Revision ID: k33a3pres0001
Revises: k33a2vat0001
Create Date: 2026-11-28 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'k33a3pres0001'
down_revision: str | None = 'k33a2vat0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('shops') as batch:
        batch.add_column(sa.Column('presentation_mode', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('example_cost_pct', sa.Integer(), nullable=False, server_default='60'))
    with op.batch_alter_table('stock_movements') as batch:
        batch.add_column(sa.Column('example', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('stock_movements') as batch:
        batch.drop_column('example')
    with op.batch_alter_table('shops') as batch:
        batch.drop_column('example_cost_pct')
        batch.drop_column('presentation_mode')
