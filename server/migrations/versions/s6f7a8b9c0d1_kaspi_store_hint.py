"""Подсказка кода склада Kaspi из данных заказов (К-7, 22.11). Новая nullable-колонка; не значение, а подсказка.

Revision ID: s6f7a8b9c0d1
Revises: r5e6f7a8b9c0
Create Date: 2026-11-22 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 's6f7a8b9c0d1'
down_revision: str | None = 'r5e6f7a8b9c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('kaspi_connections', sa.Column('store_hint', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('kaspi_connections', 'store_hint')
