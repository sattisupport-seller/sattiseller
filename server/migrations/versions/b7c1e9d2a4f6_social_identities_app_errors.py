"""AUD-11: таблицы входа через Apple/Google и журнала ошибок есть в моделях, но не в миграциях

Раньше их создавал только create_all при старте. На базе, поднятой миграциями, вход через провайдера
падал бы: таблицы social_identities не было.

Revision ID: b7c1e9d2a4f6
Revises: a6d2e8f1c3b7
Create Date: 2026-11-20 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c1e9d2a4f6'
down_revision: str | None = 'a6d2e8f1c3b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'social_identities',
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('subject', sa.String(length=128), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('provider', 'subject'),
    )
    op.create_index('ix_social_identities_user_id', 'social_identities', ['user_id'], unique=False)
    op.create_table(
        'app_errors',
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('exc_type', sa.String(length=120), nullable=False),
        sa.Column('where', sa.String(length=160), nullable=False),
        sa.Column('message', sa.String(length=300), nullable=False),
        sa.Column('app_version', sa.String(length=32), nullable=True),
        sa.Column('platform', sa.String(length=16), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('fingerprint'),
    )


def downgrade() -> None:
    op.drop_table('app_errors')
    op.drop_index('ix_social_identities_user_id', table_name='social_identities')
    op.drop_table('social_identities')
