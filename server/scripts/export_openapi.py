"""Выгрузка OpenAPI-схемы в файл для генерации типов приложения (ТЗ 2.1, задача 1).

Запуск из папки server:  .venv\\Scripts\\python.exe scripts\\export_openapi.py ..\\mobile\\src\\api\\openapi.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "mobile" / "src" / "api" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"схема записана: {target} ({len(schema.get('paths', {}))} путей)")


if __name__ == "__main__":
    main()
