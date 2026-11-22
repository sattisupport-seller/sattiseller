"""Загрузка server/.env: значения из файла, комментарии в конце строки, пустые значения не затирают, окружение главнее."""

import os

from app.config import _load_env_file


def test_env_file_values_are_loaded_and_comments_stripped(tmp_path, monkeypatch):
    monkeypatch.delenv("SATTI_TEST_A", raising=False)
    monkeypatch.delenv("SATTI_TEST_B", raising=False)
    monkeypatch.delenv("SATTI_TEST_C", raising=False)
    monkeypatch.setenv("SATTI_TEST_C", "from-env")
    f = tmp_path / ".env"
    f.write_text("# комментарий\nSATTI_TEST_A=value-a   # пояснение\nSATTI_TEST_B=\nSATTI_TEST_C=from-file\n", encoding="utf-8")
    _load_env_file(f)
    assert os.environ["SATTI_TEST_A"] == "value-a"
    assert "SATTI_TEST_B" not in os.environ  # пустое значение не записывается
    assert os.environ["SATTI_TEST_C"] == "from-env"  # уже заданное в окружении не перезаписывается


def test_missing_file_is_ignored(tmp_path):
    _load_env_file(tmp_path / "absent.env")  # не должно падать
