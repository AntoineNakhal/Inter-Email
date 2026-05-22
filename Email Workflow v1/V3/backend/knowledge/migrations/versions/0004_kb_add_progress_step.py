"""Add progress_step to kb_documents.

Stores the current ingestion stage name while status=processing so the
review modal can render a granular progress bar (extracting → chunking →
embedding → persisting → metadata) instead of a generic spinner.

Idempotent — skips the ALTER if the column already exists.

Revision ID: kb_0004
Revises: kb_0003
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "kb_0004"
down_revision: Union[str, None] = "kb_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if _column_exists("kb_documents", "progress_step"):
        return
    op.add_column(
        "kb_documents",
        sa.Column("progress_step", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    if not _column_exists("kb_documents", "progress_step"):
        return
    op.drop_column("kb_documents", "progress_step")
