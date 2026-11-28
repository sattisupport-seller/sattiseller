"""Сверка с выгрузкой Kaspi Pay «Продажи» (К-33, Б1): строки выгрузки по заказам.

Revision ID: k33b1pay0001
Revises: k33a4stock0001
Create Date: 2026-11-28 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'k33b1pay0001'
down_revision: str | None = 'k33a4stock0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'kaspi_pay_rows',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('shop_id', sa.String(length=32), nullable=False),
        sa.Column('order_number', sa.String(length=32), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=True),
        sa.Column('commission_minor', sa.BigInteger(), nullable=True),
        sa.Column('delivery_minor', sa.BigInteger(), nullable=True),
        sa.Column('payout_minor', sa.BigInteger(), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'order_number', name='uq_kaspi_pay_order'),
    )
    op.create_index('ix_kaspi_pay_rows_shop_id', 'kaspi_pay_rows', ['shop_id'])


def downgrade() -> None:
    op.drop_index('ix_kaspi_pay_rows_shop_id', table_name='kaspi_pay_rows')
    op.drop_table('kaspi_pay_rows')
