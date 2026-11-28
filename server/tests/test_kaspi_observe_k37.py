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


def test_sync_logs_response_shapes_without_values(client, demo, kaspi_on, mock, caplog):  # noqa: F811
    """KASPI_TEST §9: структура ответов по видам запросов (заказы, позиции, связи товара) — только поля и типы."""
    _connect(client, demo)
    mock.generate(4, now=datetime.now(timezone.utc), days=3, products=2)
    attrs = mock.orders[0]["attributes"]
    attrs.update({"customer": {"firstName": "Айгуль", "cellPhone": "+77010000000"},
                  "kaspiDelivery": {"courierTransmissionDate": 1764300000000, "waybill": "SECRET-WAYBILL-77"}})
    with caplog.at_level("INFO", logger="satti.kaspi"):
        r = client.post(f"/v1/shops/{demo['shop_id']}/kaspi/sync", headers=demo["headers"])
    assert r.status_code == 200, r.text
    shapes = [rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("kaspi shape")]
    kinds = {m.split()[3] for m in shapes}
    assert "orders" in kinds and "orders/{id}/entries" in kinds, kinds
    orders = next(m for m in shapes if m.split()[3] == "orders")
    assert '"customer": {"cellPhone": "str", "firstName": "str"}' in orders
    assert '"courierTransmissionDate": "int"' in orders and '"waybill": "str"' in orders
    text = caplog.text
    for secret in ("Айгуль", "+77010000000", "SECRET-WAYBILL-77", "1764300000000", VALID_TOKEN):
        assert secret not in text
    observed = next(rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("kaspi observed"))
    assert "courierTransmissionDate:" in observed and "1/" in observed  # у одного заказа признак передачи есть


def test_shape_merge_rules():
    from app.kaspi_client import KaspiClient as K
    assert K._path_kind("orders/584110157/entries") == "orders/{id}/entries"
    assert K._path_kind("masterproducts/abc123XYZ/merchantProduct") == "masterproducts/{id}/merchantProduct"
    assert K._path_kind("masterproducts/M0/merchantProduct") == "masterproducts/{id}/merchantProduct"
    assert K._path_kind("masterproducts/M0") == "masterproducts/{id}"
    assert K._path_kind("orders") == "orders"
    assert K._shape({"a": [{"x": 1}, {"y": None}], "b": "s"}) == {"a": [{"x": "int", "y": "null"}], "b": "str"}
    assert K._merge({"v": "int"}, {"v": "null"}) == {"v": "int|null"}
    assert K._merge({"v": {"a": "int"}}, {"v": "str"}) == {"v": "mixed"}
