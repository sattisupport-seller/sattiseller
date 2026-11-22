"""Склад: остатки товара, внесённые продавцом вручную (PROPOSALS пункт 18, решение владельца 22.11)

Revision ID: o2b3c4d5e6f7
Revises: n1a2b3c4d5e6
Create Date: 2026-11-22 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'o2b3c4d5e6f7'
down_revision: str | None = 'n1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'product_stocks',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('shop_id', sa.String(length=32), sa.ForeignKey('shops.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(length=32), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('product_id', name='uq_product_stock_product'),
    )
    op.create_index('ix_product_stocks_shop_id', 'product_stocks', ['shop_id'])
    op.create_index('ix_product_stocks_product_id', 'product_stocks', ['product_id'])


def downgrade() -> None:
    op.drop_index('ix_product_stocks_product_id', table_name='product_stocks')
    op.drop_index('ix_product_stocks_shop_id', table_name='product_stocks')
    op.drop_table('product_stocks')
