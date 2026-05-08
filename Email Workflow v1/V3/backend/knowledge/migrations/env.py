"""Alembic environment for the Knowledge Base database.

This is a SECOND, completely independent migration chain — distinct from
the main app's chain at `backend/persistence/migrations/`. The two chains
NEVER share metadata; cross-importing them would cause Alembic to think KB
tables belong on the main DB (and vice-versa).

Run with:
    alembic -c backend/knowledge/alembic.ini upgrade head

Most of the time you don't run this manually — `init_kb_database()` runs
it on app startup.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models registers them on KbBase.metadata for autogenerate.
from backend.knowledge.models import KbBase  # noqa: F401
from backend.knowledge.models import (  # noqa: F401
    KbChunkModel,
    KbDocumentModel,
)

config = context.config

# Honour KB_DATABASE_URL env var so the same alembic.ini works locally and
# in docker-compose (where the URL points at `kb-postgres`).
_db_url = os.getenv("KB_DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = KbBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
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
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
