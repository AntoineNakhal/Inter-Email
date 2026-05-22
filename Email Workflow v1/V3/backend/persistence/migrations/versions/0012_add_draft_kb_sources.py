"""Add kb_sources_json to drafts.

Stores the list of Knowledge Base chunks the AI cited when generating a
draft, so the user can see exactly which product-doc snippets backed the
reply. JSON-encoded into a Text column to stay portable between
Postgres and SQLite.

Idempotent: skips the ALTER if the column already exists. Useful when a
previous attempt partially succeeded (column added but alembic_version
not bumped), or when the schema was bootstrapped via create_all() on a
DB where the model already declared this column.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if _column_exists("drafts", "kb_sources_json"):
        # Column already present — nothing to do, just record the
        # revision as applied so future migrations chain cleanly.
        return
    with op.batch_alter_table("drafts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kb_sources_json",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    if not _column_exists("drafts", "kb_sources_json"):
        return
    with op.batch_alter_table("drafts") as batch_op:
        batch_op.drop_column("kb_sources_json")
