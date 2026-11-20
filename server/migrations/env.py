"""Миграции Alembic. Строка подключения — из app.config (DATABASE_URL)."""

import os
from logging.config import fileConfig

from alembic import context

# AUD-11: регистрируем таблицы всех модулей, иначе autogenerate предложит удалить подписки, админку и коды
from app import admin, billing, errorlog, models, social_auth  # noqa: F401
from app.config import settings
from app.db import Base

config = context.config

# QA-12: откат миграций удаляет данные. Без явного флага откат отказывает; копия — scripts/backup.py create
_cmd = getattr(config, "cmd_opts", None)
if _cmd is not None and getattr(_cmd, "cmd", None) and getattr(_cmd.cmd[0], "__name__", "") == "downgrade":
    if os.environ.get("SATTI_ALLOW_DOWNGRADE") != "1":
        raise SystemExit("Откат миграций удаляет данные. Для намеренного отката задайте SATTI_ALLOW_DOWNGRADE=1 "
                         "(сначала копия: python scripts/backup.py create).")
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
