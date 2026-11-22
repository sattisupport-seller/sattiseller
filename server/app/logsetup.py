"""Журнал сервера (4.2): ротация файлов по размеру.

SATTI_LOG_FILE — путь к файлу журнала (если не задан — stderr, как раньше).
SATTI_LOG_MAX_MB — размер одного файла до ротации (по умолчанию 10 МБ).
SATTI_LOG_BACKUPS — сколько старых файлов хранить (по умолчанию 5).
В журнал не пишем тела запросов и ключи: форматтер выводит только время, уровень, имя логгера и сообщение.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_TAG = "_satti_handler"


def configure_logging() -> logging.Handler:
    """Настраивает корневой логгер один раз. Возвращает установленный обработчик."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_TAG, False):
            return h
    path = os.environ.get("SATTI_LOG_FILE", "").strip()
    if path:
        max_bytes = int(float(os.environ.get("SATTI_LOG_MAX_MB", "10")) * 1024 * 1024)
        backups = int(os.environ.get("SATTI_LOG_BACKUPS", "5"))
        handler: logging.Handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT))
    setattr(handler, _HANDLER_TAG, True)
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    return handler
