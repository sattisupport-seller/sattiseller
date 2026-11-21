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
    from .config import production_config_problems

    problems = production_config_problems()
    if problems:
        raise RuntimeError("Запуск отменён, конфигурация небезопасна: " + "; ".join(problems))
    init_db()
    # 1.16: шаблон демо создаётся при запуске, а не при первом наплыве запросов (иначе все они генерируют его сразу)
    from .db import SessionLocal
    from .demo_template import ensure_template

    with SessionLocal() as template_db:
        ensure_template(template_db)
    from .scheduler import start_builtin_scheduler, stop_builtin_scheduler

    start_builtin_scheduler()
    yield
    stop_builtin_scheduler()


app = FastAPI(
    title="Satti Seller API",
    version="1.0.0",
    description="Внутренний API Satti (docs/spec.md, раздел 5). Это не методы Kaspi.",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # страницы /admin, /privacy, /terms — без внешних ресурсов. Скрипты — только свои файлы (AUD-25);
    # инлайн-стили остаются, их используют страницы
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'self'"),
}


@app.middleware("http")
async def _security_headers(request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response

from fastapi import Request as _Request  # noqa: E402
from .db import SessionLocal as _SessionLocal  # noqa: E402
from .errorlog import admin_router as _err_admin, router as _err_router, unhandled_error_response  # noqa: E402


async def _unhandled(request: _Request, exc: Exception):
    db = _SessionLocal()
    try:
        return unhandled_error_response(request, exc, db)
    finally:
        db.close()


app.add_exception_handler(Exception, _unhandled)
# CORS только для веб-разработки (localhost). Нативные приложения CORS не используют.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("SATTI_CORS_ORIGINS", "http://localhost:8081,http://127.0.0.1:8081").split(",") if o],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api, prefix="/v1")

from .web import router as web_router  # noqa: E402  (страницы политики, условий, удаление аккаунта)

app.include_router(web_router)
app.include_router(_err_router, prefix="/v1")
app.include_router(_err_admin, prefix="/v1")


@app.get("/v1/health", tags=["служебное"])
def health() -> dict[str, str]:
    return {"status": "ok"}
