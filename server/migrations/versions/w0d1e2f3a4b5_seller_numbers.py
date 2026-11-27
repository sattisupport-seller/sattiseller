"""Номер продавца, особые условия доступа, окно восстановления токена Kaspi (К-21).

Revision ID: w0d1e2f3a4b5
Revises: v9c0d1e2f3a4
Create Date: 2026-11-23 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'w0d1e2f3a4b5'
down_revision: str | None = 'v9c0d1e2f3a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'seller_numbers',
        sa.Column('number', sa.String(length=8), nullable=False),
        sa.Column('seller_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=True),
        sa.Column('shop_id', sa.String(length=32), nullable=True),
        sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('number'),
        sa.UniqueConstraint('seller_hash'),
    )
    op.create_index('ix_seller_numbers_user_id', 'seller_numbers', ['user_id'])
    op.create_table(
        'special_access',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('number', sa.String(length=8), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comment', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_special_access_number', 'special_access', ['number'])
    op.add_column('kaspi_connections', sa.Column('reconnect_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('kaspi_connections', 'reconnect_until')
    op.drop_index('ix_special_access_number', table_name='special_access')
    op.drop_table('special_access')
    op.drop_index('ix_seller_numbers_user_id', table_name='seller_numbers')
    op.drop_table('seller_numbers')
