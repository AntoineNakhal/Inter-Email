"""Alembic environment — wires our SQLAlchemy models to the migration engine.

Run migrations with:
    alembic upgrade head
    alembic downgrade -1
    alembic revision --autogenerate -m "describe_change"
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Import ALL models so every table is registered in Base.metadata.
# Alembic's --autogenerate compares Base.metadata against the live DB — if a
# model is not imported here it will be silently ignored and will go missing
# from generated migrations.
# ---------------------------------------------------------------------------
from backend.persistence.models import Base  # noqa: F401
from backend.persistence.models import (  # noqa: F401
    DraftModel,
    EmailThreadModel,
    ReviewDecisionModel,
    RuntimeSettingsModel,
    SyncRunModel,
    ThreadAnalysisModel,
    ThreadMessageModel,
    ThreadStateModel,
)
from backend.persistence.models.contact import ContactModel, ContactThreadModel  # noqa: F401

# ---------------------------------------------------------------------------
# Alembic config object — provides access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Override sqlalchemy.url from the DATABASE_URL env var when present.
# This lets the app and Alembic share the same source of truth without
# hard-coding a URL in alembic.ini.
_db_url = os.getenv("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

# Set up Python logging from alembic.ini (honours [loggers] / [handlers]).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that --autogenerate compares against.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection.

    Useful for generating a migration script to review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render server defaults so the generated SQL is complete.
        render_as_batch=True,  # required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations in a transaction."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite does not support ALTER TABLE natively; batch mode rewrites
            # tables. Safe to leave on for Postgres too — it becomes a no-op.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
