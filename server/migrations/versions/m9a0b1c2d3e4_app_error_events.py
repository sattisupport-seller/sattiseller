"""3.10: журнал появлений ошибок сервера для правила всплеска

Revision ID: m9a0b1c2d3e4
Revises: l8f9a0b1c2d3
Create Date: 2026-11-21 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'm9a0b1c2d3e4'
down_revision: str | None = 'l8f9a0b1c2d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'app_error_events',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('fingerprint', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_app_error_events_fingerprint', 'app_error_events', ['fingerprint'])
    op.create_index('ix_app_error_events_created_at', 'app_error_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_app_error_events_created_at', table_name='app_error_events')
    op.drop_index('ix_app_error_events_fingerprint', table_name='app_error_events')
    op.drop_table('app_error_events')
