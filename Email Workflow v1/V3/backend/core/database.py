"""Database engine and session helpers."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import AppSettings, get_settings


logger = logging.getLogger(__name__)


def _engine_kwargs(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False, "timeout": 30}}
    # Postgres: pool_pre_ping re-checks the connection before handing it out,
    # recovering silently from idle-timeout drops without surfacing errors to callers.
    return {"pool_pre_ping": True}


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
    """Apply all pending Alembic migrations, bringing the schema to head.

    Safe to call on every startup:
      - Fresh DB (no tables): runs all migrations from 0001 to head.
      - Existing DB with Alembic history: applies only pending migrations.
      - Pre-Alembic DB (tables exist but no alembic_version table): stamps
        at revision 0001 so Alembic knows what the baseline looks like, then
        applies 0002 onwards.

    Falls back to create_all() only when alembic.ini cannot be located (e.g.
    unusual deploy layout) so the app can still start in degraded environments.
    """
    from alembic import command
    from alembic.config import Config

    resolved = settings or get_settings()
    resolved.ensure_runtime_directories()

    # alembic.ini lives at the project root, two levels above this file
    # (backend/core/database.py → backend/core → backend → project root).
    project_root = Path(__file__).resolve().parents[2]
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        # Unusual deploy layout — warn and fall back to create_all so the
        # application can still start.  New columns won't be added to existing
        # tables, but at least a fresh DB will have the correct schema.
        logger.warning(
            "alembic.ini not found at %s — falling back to create_all(). "
            "Run `alembic upgrade head` manually to apply pending migrations.",
            alembic_ini,
        )
        from backend.persistence.models import Base
        Base.metadata.create_all(bind=get_engine())
        return

    alembic_cfg = Config(str(alembic_ini))
    # Always override the DB URL from our settings so alembic.ini's default
    # value never wins over the real configured URL.
    alembic_cfg.set_main_option("sqlalchemy.url", resolved.database_url)
    # Use an absolute script_location so the migration files are found
    # regardless of the process working directory.
    alembic_cfg.set_main_option(
        "script_location",
        str(project_root / "backend" / "persistence" / "migrations"),
    )

    engine = get_engine()
    with engine.connect() as conn:
        insp = inspect(conn)
        tables_exist = insp.has_table("email_threads")
        version_table_exists = insp.has_table("alembic_version")

        def _column_names(table: str) -> set[str]:
            if not insp.has_table(table):
                return set()
            return {col["name"] for col in insp.get_columns(table)}

        def _detect_pre_alembic_baseline() -> str:
            """Pick the highest migration revision already reflected in columns."""
            baseline = "0001"
            analysis_cols = _column_names("thread_analyses")
            runtime_cols = _column_names("runtime_settings")
            sync_cols = _column_names("sync_runs")

            if "needs_next_action" in analysis_cols:
                baseline = "0002"
            if "gmail_mailbox_name" in runtime_cols:
                baseline = "0003"
            if "mailbox_account" in sync_cols and "progress_json" in sync_cols:
                baseline = "0004"
            if "gmail_history_id" in runtime_cols:
                baseline = "0005"
            if "gmail_watch_resource_id" in runtime_cols:
                baseline = "0006"
            return baseline

    if tables_exist and not version_table_exists:
        # Pre-Alembic database: the tables were created by create_all() and
        # the old _ensure_schema() guards. Stamp at the highest revision that
        # matches the current columns so Alembic only applies missing steps.
        baseline = _detect_pre_alembic_baseline()
        logger.info(
            "Pre-Alembic database detected — stamping at revision %s "
            "before running incremental migrations.",
            baseline,
        )
        command.stamp(alembic_cfg, baseline)

    command.upgrade(alembic_cfg, "head")
    logger.info("Database schema is up to date.")
