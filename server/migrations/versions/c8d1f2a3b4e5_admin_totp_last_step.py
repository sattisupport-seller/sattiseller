"""AUD-15: последний принятый шаг TOTP — код администратора не повторяется

Revision ID: c8d1f2a3b4e5
Revises: b7c1e9d2a4f6
Create Date: 2026-11-20 13:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c8d1f2a3b4e5'
down_revision: str | None = 'b7c1e9d2a4f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('admin_totp') as batch:
        batch.add_column(sa.Column('last_step', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('admin_totp') as batch:
        batch.drop_column('last_step')
