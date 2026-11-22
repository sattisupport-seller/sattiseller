"""Журнал действий: кто (actor_id) и в каком магазине (shop_id) — только новые nullable-колонки (К-2 п.8, 22.11)

Revision ID: q4d5e6f7a8b9
Revises: p3c4d5e6f7a8
Create Date: 2026-11-22 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'q4d5e6f7a8b9'
down_revision: str | None = 'p3c4d5e6f7a8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('audit_events', sa.Column('actor_id', sa.String(length=32), nullable=True))
    op.add_column('audit_events', sa.Column('shop_id', sa.String(length=32), nullable=True))
    op.create_index('ix_audit_events_shop_id', 'audit_events', ['shop_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_events_shop_id', table_name='audit_events')
    op.drop_column('audit_events', 'shop_id')
    op.drop_column('audit_events', 'actor_id')
