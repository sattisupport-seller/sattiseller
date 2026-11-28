"""Переключатель «Я плательщик НДС» у магазина (К-33, А2).

Revision ID: k33a2vat0001
Revises: a4b5c6d7e8f9
Create Date: 2026-11-28 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'k33a2vat0001'
down_revision: str | None = 'a4b5c6d7e8f9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('shops') as batch:
        batch.add_column(sa.Column('vat_payer', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('shops') as batch:
        batch.drop_column('vat_payer')
