"""Импорт прайса продавца из кабинета Kaspi (К-16.3, 22.11): новая таблица kaspi_catalogs.

Revision ID: t7a8b9c0d1e2
Revises: s6f7a8b9c0d1
Create Date: 2026-11-22 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 't7a8b9c0d1e2'
down_revision: str | None = 's6f7a8b9c0d1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'kaspi_catalogs',
        sa.Column('shop_id', sa.String(length=32), sa.ForeignKey('shops.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('xml_text', sa.Text(), nullable=False),
        sa.Column('offers_count', sa.Integer(), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('kaspi_catalogs')
