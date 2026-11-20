"""AUD-16: отметка пробного периода уникальна по (вид, хеш) — параллельные запросы не дают два пробных периода

Revision ID: d9e2a3b4c5d6
Revises: c8d1f2a3b4e5
Create Date: 2026-11-20 13:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = 'd9e2a3b4c5d6'
down_revision: str | None = 'c8d1f2a3b4e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # дубликаты (если были) убираем, оставляя самую раннюю отметку
    op.execute("DELETE FROM billing_marks WHERE id NOT IN "
               "(SELECT MIN(id) FROM billing_marks GROUP BY kind, key_hash)")
    with op.batch_alter_table('billing_marks') as batch:
        batch.create_unique_constraint('uq_billing_marks_kind_key', ['kind', 'key_hash'])


def downgrade() -> None:
    with op.batch_alter_table('billing_marks') as batch:
        batch.drop_constraint('uq_billing_marks_kind_key', type_='unique')
