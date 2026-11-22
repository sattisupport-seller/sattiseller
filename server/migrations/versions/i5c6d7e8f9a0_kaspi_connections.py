"""2.4: подключение Kaspi — таблица kaspi_connections (токен зашифрован)

Revision ID: i5c6d7e8f9a0
Revises: h4b5c6d7e8f9
Create Date: 2026-11-21 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'i5c6d7e8f9a0'
down_revision: str | None = 'h4b5c6d7e8f9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'kaspi_connections',
        sa.Column('shop_id', sa.String(length=32), sa.ForeignKey('shops.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('seller_id', sa.String(length=64), nullable=False),
        sa.Column('token_enc', sa.Text(), nullable=False),
        sa.Column('price_key', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('cursor_ms', sa.BigInteger(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(length=200), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('kaspi_connections')
