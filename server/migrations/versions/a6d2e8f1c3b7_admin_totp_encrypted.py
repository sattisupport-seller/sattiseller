"""admin 2FA: секрет хранится зашифрованным (O2, отчёт QA)

Старые секреты лежали открытым текстом и не расшифровываются новым ключом,
поэтому строки admin_totp удаляются: владелец заново создаёт 2FA (POST /v1/admin/2fa/setup).

Revision ID: a6d2e8f1c3b7
Revises: f3c9d1a7e5b2
Create Date: 2026-11-21 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a6d2e8f1c3b7'
down_revision: str | None = 'f3c9d1a7e5b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('DELETE FROM admin_totp')
    with op.batch_alter_table('admin_totp') as batch:
        batch.alter_column('secret', existing_type=sa.String(length=64), type_=sa.String(length=255),
                           existing_nullable=False)


def downgrade() -> None:
    op.execute('DELETE FROM admin_totp')
    with op.batch_alter_table('admin_totp') as batch:
        batch.alter_column('secret', existing_type=sa.String(length=255), type_=sa.String(length=64),
                           existing_nullable=False)
