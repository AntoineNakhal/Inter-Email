"""Add thread_overrides table and merge-signal columns to email_threads and thread_messages.

- thread_overrides: per-user manual corrections to AI-generated analysis fields.
  Passed as soft hints on re-analysis; AI may disagree and reasons are tracked.
- email_threads.grouping_reason / merge_signals_json / source_thread_ids_json:
  persists why threads were merged so the split-thread action can reconstruct originals.
- thread_messages.original_gmail_thread_id: the Gmail thread this message came from
  before grouping, used by the split-thread action.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    def has_column(table_name: str, column_name: str) -> bool:
        return any(
            column["name"] == column_name
            for column in inspector.get_columns(table_name)
        )

    # --- thread_overrides ---
    if not inspector.has_table("thread_overrides"):
        op.create_table(
            "thread_overrides",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("thread_id", sa.Integer(), sa.ForeignKey("email_threads.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("category", sa.String(64), nullable=True),
            sa.Column("urgency", sa.String(32), nullable=True),
            sa.Column("needs_action_today", sa.Boolean(), nullable=True),
            sa.Column("waiting_on_us", sa.Boolean(), nullable=True),
            sa.Column("needs_next_action", sa.Boolean(), nullable=True),
            sa.Column("should_draft_reply", sa.Boolean(), nullable=True),
            sa.Column("relevance_bucket", sa.String(32), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # --- merge signal columns on email_threads ---
    with op.batch_alter_table("email_threads") as batch_op:
        if not has_column("email_threads", "grouping_reason"):
            batch_op.add_column(sa.Column("grouping_reason", sa.String(64), nullable=False, server_default="gmail_thread_id"))
        if not has_column("email_threads", "merge_signals_json"):
            batch_op.add_column(sa.Column("merge_signals_json", sa.Text(), nullable=False, server_default="[]"))
        if not has_column("email_threads", "source_thread_ids_json"):
            batch_op.add_column(sa.Column("source_thread_ids_json", sa.Text(), nullable=False, server_default="[]"))

    # --- original Gmail thread ID on thread_messages ---
    with op.batch_alter_table("thread_messages") as batch_op:
        if not has_column("thread_messages", "original_gmail_thread_id"):
            batch_op.add_column(sa.Column("original_gmail_thread_id", sa.String(255), nullable=False, server_default=""))

    # --- ai_override_disagreements on thread_analyses ---
    with op.batch_alter_table("thread_analyses") as batch_op:
        if not has_column("thread_analyses", "ai_override_disagreements_json"):
            batch_op.add_column(sa.Column("ai_override_disagreements_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    def has_column(table_name: str, column_name: str) -> bool:
        return any(
            column["name"] == column_name
            for column in inspector.get_columns(table_name)
        )

    with op.batch_alter_table("thread_analyses") as batch_op:
        if has_column("thread_analyses", "ai_override_disagreements_json"):
            batch_op.drop_column("ai_override_disagreements_json")

    with op.batch_alter_table("thread_messages") as batch_op:
        if has_column("thread_messages", "original_gmail_thread_id"):
            batch_op.drop_column("original_gmail_thread_id")

    with op.batch_alter_table("email_threads") as batch_op:
        if has_column("email_threads", "source_thread_ids_json"):
            batch_op.drop_column("source_thread_ids_json")
        if has_column("email_threads", "merge_signals_json"):
            batch_op.drop_column("merge_signals_json")
        if has_column("email_threads", "grouping_reason"):
            batch_op.drop_column("grouping_reason")

    if inspector.has_table("thread_overrides"):
        op.drop_table("thread_overrides")
