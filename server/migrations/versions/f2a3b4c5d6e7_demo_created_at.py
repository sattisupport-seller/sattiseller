"""ADR-0005: демо живёт 24 часа от создания — колонка created_at (заполняется из last_active_at)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-20 17:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a3b4c5d6e7'
down_revision: str | None = 'e1f2a3b4c5d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('demo_installations') as batch:
        batch.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE demo_installations SET created_at = last_active_at WHERE created_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table('demo_installations') as batch:
        batch.drop_column('created_at')
