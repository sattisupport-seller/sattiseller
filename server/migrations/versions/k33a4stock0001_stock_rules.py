"""Остатки в боевом режиме (К-33, А4): заказ передан в Kaspi Доставку, буфер автоснятия.

Revision ID: k33a4stock0001
Revises: k33a3pres0001
Create Date: 2026-11-28 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'k33a4stock0001'
down_revision: str | None = 'k33a3pres0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('in_delivery_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('product_stocks') as batch:
        batch.add_column(sa.Column('buffer', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('product_stocks') as batch:
        batch.drop_column('buffer')
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('in_delivery_at')
