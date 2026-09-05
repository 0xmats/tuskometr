from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base, PipelineState


def _ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        return
    raw_path = database_url.removeprefix(prefix)
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> Engine:
    _ensure_sqlite_parent(database_url)
    connect_args = (
        {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


settings = get_settings()
engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(target_engine)
    factory = (
        SessionLocal
        if target_engine is engine
        else sessionmaker(bind=target_engine, autoflush=False, expire_on_commit=False)
    )
    with factory() as session:
        if session.scalar(select(PipelineState).where(PipelineState.id == 1)) is None:
            session.add(PipelineState(id=1, state="offline", reconnect_count=0))
            session.commit()


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
