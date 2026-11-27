"""Деактивация аккаунта на 30 дней (К-21).

Revision ID: x1e2f3a4b5c6
Revises: w0d1e2f3a4b5
Create Date: 2026-11-27 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'x1e2f3a4b5c6'
down_revision: str | None = 'w0d1e2f3a4b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('delete_after', sa.DateTime(timezone=True), nullable=True))
        batch.create_index('ix_users_delete_after', ['delete_after'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_delete_after')
        batch.drop_column('delete_after')
        batch.drop_column('deactivated_at')
