"""3.10: журнал отправленных оповещений владельцу (одно письмо на ключ)

Revision ID: l8f9a0b1c2d3
Revises: k7e8f9a0b1c2
Create Date: 2026-11-21 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'l8f9a0b1c2d3'
down_revision: str | None = 'k7e8f9a0b1c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'owner_alert_log',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('owner_alert_log')
