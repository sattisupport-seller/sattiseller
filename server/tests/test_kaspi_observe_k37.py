"""К-37 п.4: синхронизация пишет в журнал, какие поля и статусы прислал Kaspi — без данных покупателя и без токена."""

from datetime import datetime, timezone

from app import kaspi as kaspi_service
from tests.kaspi_mock import VALID_TOKEN
from tests.test_kaspi import _connect, kaspi_on, mock  # noqa: F401 — фикстуры


def test_sync_logs_observed_fields_and_unknown_status(client, demo, kaspi_on, mock, caplog):  # noqa: F811
    _connect(client, demo)
    mock.generate(6, now=datetime.now(timezone.utc), days=3, products=2)
    mock.orders[0]["attributes"].update({"status": "SOMETHING_NEW", "state": "ARCHIVE",
                                         "customer": {"firstName": "Айгуль", "cellPhone": "+77010000000"}})
    with caplog.at_level("INFO", logger="satti.kaspi"):
        r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    text = caplog.text
    assert "kaspi observed" in text and "creationDate" in text and "status=" in text and "SOMETHING_NEW" in text
    assert "kaspi unknown status 'SOMETHING_NEW'" in text
    assert "Айгуль" not in text and "+77010000000" not in text and VALID_TOKEN not in text
    assert kaspi_service.STATE_MAP.get("SOMETHING_NEW") is None
