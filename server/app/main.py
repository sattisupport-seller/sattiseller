"""Точка входа Satti API. Запуск: uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .api import api
from .db import init_db
from .errors import ApiError, api_error_handler


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Satti Seller API",
    version="1.0.0",
    description="Внутренний API Satti (docs/spec.md, раздел 5). Это не методы Kaspi.",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)
# CORS только для веб-разработки (localhost). Нативные приложения CORS не используют.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("SATTI_CORS_ORIGINS", "http://localhost:8081,http://127.0.0.1:8081").split(",") if o],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api, prefix="/v1")


@app.get("/v1/health", tags=["служебное"])
def health() -> dict[str, str]:
    return {"status": "ok"}
