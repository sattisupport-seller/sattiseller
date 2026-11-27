"""Пуши: токены устройств и очередь уведомлений (MASTER_PLAN 3.4).

Revision ID: z3a4b5c6d7e8
Revises: y2f3a4b5c6d7
Create Date: 2026-11-27 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'z3a4b5c6d7e8'
down_revision: str | None = 'y2f3a4b5c6d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'device_tokens',
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('token'),
    )
    op.create_index('ix_device_tokens_user_id', 'device_tokens', ['user_id'])
    op.create_table(
        'push_messages',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('dedup_key', sa.String(length=128), nullable=True),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('body', sa.String(length=300), nullable=False),
        sa.Column('data_json', sa.Text(), nullable=False),
        sa.Column('send_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dropped', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedup_key'),
    )
    op.create_index('ix_push_messages_user_id', 'push_messages', ['user_id'])
    op.create_index('ix_push_messages_send_after', 'push_messages', ['send_after'])


def downgrade() -> None:
    op.drop_index('ix_push_messages_send_after', table_name='push_messages')
    op.drop_index('ix_push_messages_user_id', table_name='push_messages')
    op.drop_table('push_messages')
    op.drop_index('ix_device_tokens_user_id', table_name='device_tokens')
    op.drop_table('device_tokens')
