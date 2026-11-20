"""user age confirmation 18+ (ADR-0004)

Revision ID: e5b8c3d9a2f1
Revises: d7e2a9c1f4b3
Create Date: 2026-11-20 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5b8c3d9a2f1'
down_revision: str | None = 'd7e2a9c1f4b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('age_confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('age_confirmed_at')
