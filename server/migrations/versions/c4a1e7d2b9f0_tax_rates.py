"""tax rates (ТЗ 2.1, раздел 7)

Revision ID: c4a1e7d2b9f0
Revises: 9b8f1d579484
Create Date: 2026-11-20 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4a1e7d2b9f0'
down_revision: str | None = '9b8f1d579484'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'tax_rates',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('shop_id', sa.String(length=32), nullable=False),
        sa.Column('rate_bp', sa.Integer(), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tax_rates_shop_id'), 'tax_rates', ['shop_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tax_rates_shop_id'), table_name='tax_rates')
    op.drop_table('tax_rates')
