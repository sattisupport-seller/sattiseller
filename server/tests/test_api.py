from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_app_config_has_required_fields():
    r = client.get("/v1/app/config")
    assert r.status_code == 200
    body = r.json()
    for key in ("min_supported_version_ios", "min_supported_version_android",
                "ai_service_name", "privacy_url", "terms_url", "flags"):
        assert key in body
    assert body["flags"]["kaspi_connection"] is False


def test_openapi_available():
    assert client.get("/v1/openapi.json").status_code == 200
