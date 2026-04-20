"""Database engine and session helpers."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import AppSettings, get_settings


def _engine_kwargs(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    resolved_settings = get_settings()
    resolved_settings.ensure_runtime_directories()
    return create_engine(
        resolved_settings.database_url,
        future=True,
        **_engine_kwargs(resolved_settings.database_url),
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def init_database(settings: AppSettings | None = None) -> None:
    """Create the initial schema for local development."""

    from backend.persistence.models import Base

    (settings or get_settings()).ensure_runtime_directories()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
