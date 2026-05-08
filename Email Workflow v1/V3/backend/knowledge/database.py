"""Knowledge Base database engine + session helpers.

Mirrors `backend/core/database.py` but binds to a SECOND Postgres instance.
Why a separate engine (and not just a separate schema)?

  * Total isolation — a runaway `kb_chunks` similarity scan can't lock
    rows in `email_threads`.
  * Independent lifecycle — wiping/re-ingesting the KB never touches user data.
  * Pgvector lives only on the KB DB, so the main DB stays vanilla Postgres.

The KB is an OPTIONAL feature: when `KB_DATABASE_URL` is empty, every helper
in this module raises `KnowledgeBaseDisabledError`. Callers (services,
routers) check `is_kb_enabled()` first and either short-circuit or surface a
clean 400/503 — no silent fallbacks.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import AppSettings, get_settings


logger = logging.getLogger(__name__)


class KnowledgeBaseDisabledError(RuntimeError):
    """Raised when KB code path runs without KB_DATABASE_URL set."""


def is_kb_enabled(settings: AppSettings | None = None) -> bool:
    """Cheap predicate the rest of the app uses to gate KB access."""
    resolved = settings or get_settings()
    return bool(resolved.kb_database_url.strip())


def _engine_kwargs(database_url: str) -> dict[str, object]:
    # Pgvector requires Postgres; the KB will not work on SQLite.
    # pool_pre_ping recovers from idle-timeout drops silently.
    return {"pool_pre_ping": True}


@lru_cache(maxsize=1)
def get_kb_engine() -> Engine:
    resolved_settings = get_settings()
    if not is_kb_enabled(resolved_settings):
        raise KnowledgeBaseDisabledError(
            "KB_DATABASE_URL is not set — Knowledge Base is disabled."
        )
    return create_engine(
        resolved_settings.kb_database_url,
        future=True,
        **_engine_kwargs(resolved_settings.kb_database_url),
    )


@lru_cache(maxsize=1)
def get_kb_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_kb_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def init_kb_database(settings: AppSettings | None = None) -> None:
    """Run the KB Alembic chain and ensure the pgvector extension exists.

    Safe to call on every startup. No-op when the KB is disabled.
    """
    from alembic import command
    from alembic.config import Config

    resolved = settings or get_settings()
    if not is_kb_enabled(resolved):
        logger.info(
            "KB_DATABASE_URL not configured — skipping Knowledge Base init."
        )
        return

    # `CREATE EXTENSION IF NOT EXISTS vector` must run BEFORE the migration
    # that defines vector columns. We do it here on the live engine so it's
    # idempotent and outside Alembic's transaction scope.
    engine = get_kb_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    project_root = Path(__file__).resolve().parents[2]
    migrations_dir = project_root / "backend" / "knowledge" / "migrations"

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", resolved.kb_database_url)

    command.upgrade(alembic_cfg, "head")
    logger.info("Knowledge Base schema is up to date.")
