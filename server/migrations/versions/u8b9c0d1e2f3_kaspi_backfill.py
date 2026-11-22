"""Первая загрузка: 7 дней сразу, остальные 90 дней в фоне с прогрессом (К-18.3, 22.11).

Revision ID: u8b9c0d1e2f3
Revises: t7a8b9c0d1e2
Create Date: 2026-11-22 22:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'u8b9c0d1e2f3'
down_revision: str | None = 't7a8b9c0d1e2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # существующие подключения считаем уже догруженными (server_default true)
    op.add_column('kaspi_connections', sa.Column('backfill_done', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('kaspi_connections', sa.Column('backfill_page', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('kaspi_connections', sa.Column('load_done', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('kaspi_connections', sa.Column('load_total', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('kaspi_connections', 'load_total')
    op.drop_column('kaspi_connections', 'load_done')
    op.drop_column('kaspi_connections', 'backfill_page')
    op.drop_column('kaspi_connections', 'backfill_done')
