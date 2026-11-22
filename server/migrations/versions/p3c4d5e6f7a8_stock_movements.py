"""Журнал движений склада (К-1 от 22.11): инвентаризация и приход с датой события

Revision ID: p3c4d5e6f7a8
Revises: o2b3c4d5e6f7
Create Date: 2026-11-22 17:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'p3c4d5e6f7a8'
down_revision: str | None = 'o2b3c4d5e6f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('shop_id', sa.String(length=32), sa.ForeignKey('shops.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(length=32), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_stock_movements_shop_id', 'stock_movements', ['shop_id'])
    op.create_index('ix_stock_movements_product_id', 'stock_movements', ['product_id'])
    op.create_index('ix_stock_movements_occurred_at', 'stock_movements', ['occurred_at'])


def downgrade() -> None:
    op.drop_index('ix_stock_movements_occurred_at', table_name='stock_movements')
    op.drop_index('ix_stock_movements_product_id', table_name='stock_movements')
    op.drop_index('ix_stock_movements_shop_id', table_name='stock_movements')
    op.drop_table('stock_movements')
