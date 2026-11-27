"""Refresh token Sign in with Apple для отзыва при удалении аккаунта (MASTER_PLAN 3.3).

Revision ID: y2f3a4b5c6d7
Revises: x1e2f3a4b5c6
Create Date: 2026-11-27 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'y2f3a4b5c6d7'
down_revision: str | None = 'x1e2f3a4b5c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('social_identities') as batch:
        batch.add_column(sa.Column('refresh_token_enc', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('social_identities') as batch:
        batch.drop_column('refresh_token_enc')
