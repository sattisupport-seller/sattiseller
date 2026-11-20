"""1.19: согласие с условиями и политикой — версия и время у пользователя

Revision ID: h4b5c6d7e8f9
Revises: g3a4b5c6d7e8
Create Date: 2026-11-20 19:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'h4b5c6d7e8f9'
down_revision: str | None = 'g3a4b5c6d7e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('terms_version', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('terms_accepted_at')
        batch.drop_column('terms_version')
