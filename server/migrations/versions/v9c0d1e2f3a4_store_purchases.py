"""Покупки в App Store и Google Play и обработанные уведомления магазинов (MASTER_PLAN 3.1–3.2, К-21).

Revision ID: v9c0d1e2f3a4
Revises: u8b9c0d1e2f3
Create Date: 2026-11-23 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'v9c0d1e2f3a4'
down_revision: str | None = 'u8b9c0d1e2f3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'store_purchases',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('store', sa.String(length=16), nullable=False),
        sa.Column('purchase_key', sa.String(length=512), nullable=False),
        sa.Column('shop_id', sa.String(length=32), nullable=False),
        sa.Column('product_id', sa.String(length=128), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store', 'purchase_key', name='uq_store_purchases_key'),
    )
    op.create_index('ix_store_purchases_shop_id', 'store_purchases', ['shop_id'])
    op.create_table(
        'store_notifications',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('store', sa.String(length=16), nullable=False),
        sa.Column('event_id', sa.String(length=128), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('result', sa.String(length=32), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store', 'event_id', name='uq_store_notifications_event'),
    )


def downgrade() -> None:
    op.drop_table('store_notifications')
    op.drop_index('ix_store_purchases_shop_id', table_name='store_purchases')
    op.drop_table('store_purchases')
