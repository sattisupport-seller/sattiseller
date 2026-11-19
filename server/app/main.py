"""Satti API, версия /v1 (docs/spec.md, раздел 5). Этап A: только служебные методы."""

from fastapi import FastAPI

from .config import AppConfig, get_app_config

app = FastAPI(title="Satti Seller API", version="0.1.0", openapi_url="/v1/openapi.json",
              docs_url="/v1/docs")


@app.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/app/config", response_model=AppConfig)
def app_config() -> AppConfig:
    return get_app_config()
