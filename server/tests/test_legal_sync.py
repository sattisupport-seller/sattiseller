"""Тексты /privacy и /terms в пакете сервера совпадают с исходниками в docs/legal (ТЗ 2.1, 13.2)."""

from pathlib import Path

import pytest

from app.web import LEGAL_DIR

DOCS = Path(__file__).resolve().parents[2] / "docs" / "legal"


@pytest.mark.parametrize("name", ["privacy-policy-draft.md", "terms-draft.md"])
def test_packaged_legal_text_exists_and_matches_source(name):
    packaged = LEGAL_DIR / name
    assert packaged.exists()
    if DOCS.exists():  # в репозитории исходники есть; на сервере папки docs может не быть
        assert packaged.read_text(encoding="utf-8") == (DOCS / name).read_text(encoding="utf-8")
