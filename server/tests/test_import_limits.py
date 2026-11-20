"""AUD-06: большой файл отклоняется быстро; распакованный размер считается по фактическим байтам."""

import io
import time

from openpyxl import Workbook

from app.config import settings

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["sku", "purchase"])
    for i in range(rows):
        ws.append([f"S{i}", 100])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_over_row_limit_is_rejected_fast(client, demo, monkeypatch):
    monkeypatch.setattr(settings, "import_max_rows", 50)
    body = _xlsx(5000)
    t0 = time.time()
    r = client.post(f"/v1/shops/{demo['shop_id']}/imports", headers=demo["headers"],
                    files={"file": ("big.xlsx", body, XLSX_MIME)})
    elapsed = time.time() - t0
    assert r.status_code == 400
    assert elapsed < 20  # раньше разбор шёл до конца таблицы; теперь останавливается на лимите


def test_unzipped_size_counts_real_bytes(client, demo, monkeypatch):
    # заголовки архива здесь не при чём: лимит проверяется по распакованным данным
    monkeypatch.setattr(settings, "import_max_unzipped_bytes", 1000)
    r = client.post(f"/v1/shops/{demo['shop_id']}/imports", headers=demo["headers"],
                    files={"file": ("small.xlsx", _xlsx(200), XLSX_MIME)})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "import_too_large"


def test_normal_xlsx_still_imports(client, demo):
    r = client.post(f"/v1/shops/{demo['shop_id']}/imports", headers=demo["headers"],
                    files={"file": ("ok.xlsx", _xlsx(20), XLSX_MIME)})
    assert r.status_code == 201, r.text
    assert r.json()["rows_total"] == 20
