"""Коды складов Kaspi (storeId) для наличия в XML-прайсе (К-6 п.3, 22.11). Новая nullable-колонка.

Revision ID: r5e6f7a8b9c0
Revises: q4d5e6f7a8b9
Create Date: 2026-11-22 19:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'r5e6f7a8b9c0'
down_revision: str | None = 'q4d5e6f7a8b9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('kaspi_connections', sa.Column('store_ids', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('kaspi_connections', 'store_ids')
