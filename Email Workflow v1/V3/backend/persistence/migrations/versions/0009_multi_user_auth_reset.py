"""Reset schema for multi-user auth and ownership.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

from backend.persistence.models import Base


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES_TO_DROP = [
    "eta_progress",
    "user_sessions",
    "contact_threads",
    "contacts",
    "drafts",
    "review_decisions",
    "thread_states",
    "thread_analyses",
    "thread_messages",
    "email_threads",
    "runtime_settings",
    "sync_runs",
    "users",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table_name in TABLES_TO_DROP:
        if inspector.has_table(table_name):
            op.drop_table(table_name)
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table_name in TABLES_TO_DROP:
        if inspector.has_table(table_name):
            op.drop_table(table_name)
