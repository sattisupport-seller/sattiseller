"""admin panel: 2FA secrets, feature flags, account block, support access (ТЗ 2.1, раздел 14)

Revision ID: f3c9d1a7e5b2
Revises: e5b8c3d9a2f1
Create Date: 2026-11-20 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f3c9d1a7e5b2'
down_revision: str | None = 'e5b8c3d9a2f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'admin_totp',
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('secret', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'feature_flags',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('support_access_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('support_access_until')
        batch.drop_column('blocked_at')
    op.drop_table('feature_flags')
    op.drop_table('admin_totp')
