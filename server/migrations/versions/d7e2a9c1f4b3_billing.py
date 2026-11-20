"""billing: subscriptions, billing marks, retention events (ТЗ 2.1, разделы 8–9)

Revision ID: d7e2a9c1f4b3
Revises: c4a1e7d2b9f0
Create Date: 2026-11-20 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd7e2a9c1f4b3'
down_revision: str | None = 'c4a1e7d2b9f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'subscriptions',
        sa.Column('shop_id', sa.String(length=32), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('access_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('store', sa.String(length=16), nullable=False),
        sa.Column('lapsed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('shop_id'),
    )
    op.create_table(
        'billing_marks',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_billing_marks_key_hash'), 'billing_marks', ['key_hash'], unique=False)
    op.create_table(
        'retention_events',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('shop_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_retention_events_shop_id'), 'retention_events', ['shop_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_retention_events_shop_id'), table_name='retention_events')
    op.drop_table('retention_events')
    op.drop_index(op.f('ix_billing_marks_key_hash'), table_name='billing_marks')
    op.drop_table('billing_marks')
    op.drop_table('subscriptions')
