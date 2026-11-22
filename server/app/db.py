from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .sqlfuncs import register_sqlite


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # 1.16: пул должен быть больше числа рабочих потоков FastAPI (40). Иначе потоки ждут соединение,
        # удерживая другие, и закрыть сессию (нужен ещё один поток) некому: при 100 одновременных запросах сервер вставал.
        kwargs.update(pool_size=20, max_overflow=40)
    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
            register_sqlite(dbapi_conn)  # 1.16: функции для копирования демо-шаблона
    return engine


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  регистрирует таблицы

    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
