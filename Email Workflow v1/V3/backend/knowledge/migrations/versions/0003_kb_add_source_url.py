"""Add source_url to kb_documents (for YouTube and other remote sources).

Idempotent — same defensive pattern as the rest of our migrations.

Revision ID: kb_0003
Revises: kb_0002
Create Date: 2026-05-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "kb_0003"
down_revision: Union[str, None] = "kb_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if _column_exists("kb_documents", "source_url"):
        return
    op.add_column(
        "kb_documents",
        sa.Column("source_url", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    if not _column_exists("kb_documents", "source_url"):
        return
    op.drop_column("kb_documents", "source_url")
