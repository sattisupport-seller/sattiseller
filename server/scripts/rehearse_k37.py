"""Репетиция К-37 на имитации Kaspi: путь нового продавца (код из письма → магазин → подключение → загрузка),
журнал в файл, затем сводка kaspi_watch по этому журналу и базе. Отдельная временная база; реальный Kaspi не трогается.

  python scripts/rehearse_k37.py [папка]   (по умолчанию — новая временная папка)
"""
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

WORK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="satti-k37-"))
SERVER = Path(__file__).resolve().parents[1]
WORK.mkdir(parents=True, exist_ok=True)
db = WORK / "rehearse.db"
log = WORK / "rehearse.log"
for p in (db, log):
    if p.exists():
        p.unlink()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{db.as_posix()}",
    "KASPI_ENABLED": "1",
    "SATTI_EMAIL_LOGIN": "1",
    "SATTI_LOG_FILE": str(log),
    "SATTI_DATA_DIR": str(WORK / "data"),
})
os.chdir(SERVER)
sys.path.insert(0, str(SERVER))

subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, capture_output=True)

from fastapi.testclient import TestClient  # noqa: E402

from app import api as api_module  # noqa: E402
from app import kaspi as kaspi_service  # noqa: E402
from app.kaspi_client import KaspiClient  # noqa: E402
from app.main import app  # noqa: E402
from tests.conftest import confirm_age, login  # noqa: E402
from tests.kaspi_mock import VALID_TOKEN, MockKaspi  # noqa: E402
from tests.test_kaspi import _set_admin_flag  # noqa: E402

m = MockKaspi()
m.generate(470, now=datetime.now(timezone.utc), days=89, products=25)
m.orders[3]["attributes"]["kaspiDelivery"] = {"courierTransmissionDate": 1764300000000}


def factory(token, **kw):
    return KaspiClient(token, transport=m.transport(), sleep=lambda s: None, min_interval=0)


api_module.KaspiClient = factory
kaspi_service.client_for = lambda conn: factory(kaspi_service.decrypt_token(conn.token_enc))
_set_admin_flag(True)

c = TestClient(app)
tok = login(c, "kaspi-rehearsal@example.com")
h = {"Authorization": f"Bearer {tok['access_token']}"}
confirm_age(c, h)
r = c.post("/v1/shops", headers=h, json={"name": "Репетиция", "timezone": "Asia/Almaty", "language": "ru"})
assert r.status_code in (200, 201), r.text
shop = r.json()["id"]
print("onboarding", c.post("/v1/me/onboarding/complete", headers=h).status_code)
r = c.post(f"/v1/shops/{shop}/kaspi/connection", headers=h, json={"seller_id": "S-1", "token": VALID_TOKEN})
print("connect", r.status_code, r.text[:200])
t0 = time.time()
r = c.post(f"/v1/shops/{shop}/kaspi/sync", headers=h)
print("sync", r.status_code, r.text[:300], f"{time.time() - t0:.1f}s")
print("connection", c.get(f"/v1/shops/{shop}/kaspi/connection", headers=h).json())
for path in ("overview?period=30d", "money", "stock"):
    r = c.get(f"/v1/shops/{shop}/{path}", headers=h)
    print(path, r.status_code, r.text[:160].replace("\n", " "))
print("methods seen by mock:", sorted({mth for mth, _ in m.methods_seen}))
print("token in log:", VALID_TOKEN in log.read_text(encoding="utf-8"))
print("=" * 30)
subprocess.run([sys.executable, "scripts/kaspi_watch.py", "--log", str(log), "--db", str(db)], check=False)
