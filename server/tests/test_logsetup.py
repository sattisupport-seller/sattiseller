"""4.2: журнал сервера — ротация по размеру; без SATTI_LOG_FILE — stderr; повторный вызов не дублирует обработчик."""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from app import logsetup


@pytest.fixture
def clean_root(monkeypatch):
    """Снимает обработчик, который поставил импорт main.py, и возвращает корневой логгер в исходное состояние."""
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        if getattr(h, "_satti_handler", False):
            root.removeHandler(h)
    yield root
    for h in list(root.handlers):
        if h not in saved:
            root.removeHandler(h)
            h.close()
    for h in saved:
        if h not in root.handlers:
            root.addHandler(h)


def test_file_log_rotates_by_size(tmp_path, monkeypatch, clean_root):
    path = tmp_path / "server.log"
    monkeypatch.setenv("SATTI_LOG_FILE", str(path))
    monkeypatch.setenv("SATTI_LOG_MAX_MB", "0.001")  # ~1 КБ, чтобы ротация случилась в тесте
    monkeypatch.setenv("SATTI_LOG_BACKUPS", "2")
    handler = logsetup.configure_logging()
    assert isinstance(handler, RotatingFileHandler)
    log = logging.getLogger("satti.test")
    for i in range(200):
        log.warning("строка %s %s", i, "x" * 40)
    handler.flush()
    assert path.exists() and (tmp_path / "server.log.1").exists()
    assert not (tmp_path / "server.log.3").exists()  # не больше SATTI_LOG_BACKUPS копий


def test_configure_is_idempotent(tmp_path, monkeypatch, clean_root):
    monkeypatch.setenv("SATTI_LOG_FILE", str(tmp_path / "a.log"))
    first = logsetup.configure_logging()
    second = logsetup.configure_logging()
    assert first is second
    tagged = [h for h in clean_root.handlers if getattr(h, "_satti_handler", False)]
    assert len(tagged) == 1


def test_without_file_uses_stderr(monkeypatch, clean_root):
    monkeypatch.delenv("SATTI_LOG_FILE", raising=False)
    handler = logsetup.configure_logging()
    assert isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
