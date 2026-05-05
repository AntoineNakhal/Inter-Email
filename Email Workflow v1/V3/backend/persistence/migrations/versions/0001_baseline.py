"""Baseline: full schema from all SQLAlchemy models.

This is the starting migration. It creates all 10 tables that were previously
built via create_all() in core/database.py and inline ALTER TABLE calls in
thread_repository._ensure_schema().

Once this migration has been applied, new schema changes must be added as
additional versioned migrations — never via ALTER TABLE in application code.

Revision ID: 0001
Revises: (none — baseline)
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables are created in dependency order: referenced tables first.

    # ------------------------------------------------------------------
    # email_threads — the core product unit
    # ------------------------------------------------------------------
    op.create_table(
        "email_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("external_thread_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("participants_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_message_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("combined_thread_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("security_status", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("sensitivity_markers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("latest_message_from_me", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("latest_message_from_external", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("latest_message_has_question", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("latest_message_has_action_request", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("waiting_on_us", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("resolved_or_closed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("relevance_bucket", sa.String(32), nullable=True),
        sa.Column("included_in_ai", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("ai_decision", sa.String(64), nullable=True),
        sa.Column("ai_decision_reason", sa.Text(), nullable=True),
        sa.Column("analysis_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("signature", sa.String(128), nullable=False, server_default=""),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_email_threads_external_thread_id",
        "email_threads",
        ["external_thread_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # thread_messages — individual Gmail messages (cleaned)
    # ------------------------------------------------------------------
    op.create_table(
        "thread_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id"),
            nullable=False,
        ),
        sa.Column("external_message_id", sa.String(255), nullable=False),
        sa.Column("sender", sa.String(500), nullable=False, server_default=""),
        sa.Column("recipients_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("cleaned_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("label_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_thread_messages_thread_id", "thread_messages", ["thread_id"])
    op.create_index(
        "ix_thread_messages_external_message_id",
        "thread_messages",
        ["external_message_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # thread_analyses — AI analysis results + verification (1:1 per thread)
    # ------------------------------------------------------------------
    op.create_table(
        "thread_analyses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False, server_default=""),
        sa.Column("urgency", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_status", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_action_today", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("should_draft_reply", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("draft_needs_date", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("draft_date_reason", sa.Text(), nullable=True),
        sa.Column("draft_needs_attachment", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("draft_attachment_reason", sa.Text(), nullable=True),
        sa.Column("crm_contact_name", sa.String(255), nullable=True),
        sa.Column("crm_company", sa.String(255), nullable=True),
        sa.Column("crm_opportunity_type", sa.String(255), nullable=True),
        sa.Column("crm_urgency", sa.String(32), nullable=True),
        sa.Column("provider_name", sa.String(64), nullable=False, server_default="heuristic"),
        sa.Column(
            "model_name",
            sa.String(128),
            nullable=False,
            server_default="deterministic-fallback",
        ),
        sa.Column("prompt_version", sa.String(64), nullable=False, server_default="v1"),
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("accuracy_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column(
            "verifier_provider_name",
            sa.String(64),
            nullable=False,
            server_default="heuristic",
        ),
        sa.Column(
            "verifier_model_name",
            sa.String(128),
            nullable=False,
            server_default="deterministic-fallback",
        ),
        sa.Column("verifier_used_fallback", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_thread_analyses_thread_id",
        "thread_analyses",
        ["thread_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # thread_states — per-thread UI state (seen, pinned)
    # ------------------------------------------------------------------
    op.create_table(
        "thread_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id"),
            nullable=False,
        ),
        sa.Column("seen", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("seen_version", sa.String(128), nullable=False, server_default=""),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_thread_states_thread_id",
        "thread_states",
        ["thread_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # drafts — AI-generated reply drafts (many per thread, latest used)
    # ------------------------------------------------------------------
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_name", sa.String(64), nullable=False, server_default="heuristic"),
        sa.Column(
            "model_name",
            sa.String(128),
            nullable=False,
            server_default="deterministic-fallback",
        ),
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_drafts_thread_id", "drafts", ["thread_id"])

    # ------------------------------------------------------------------
    # review_decisions — internal human review outcomes (append-only)
    # ------------------------------------------------------------------
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id"),
            nullable=False,
        ),
        sa.Column("queue_belongs", sa.String(32), nullable=False, server_default="not_sure"),
        sa.Column("merge_correct", sa.String(32), nullable=False, server_default="not_sure"),
        sa.Column("summary_useful", sa.String(32), nullable=False, server_default="partially"),
        sa.Column("next_action_useful", sa.String(32), nullable=False, server_default="partially"),
        sa.Column("draft_useful", sa.String(32), nullable=False, server_default="partially"),
        sa.Column("crm_useful", sa.String(32), nullable=False, server_default="not_applicable"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("improvement_tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_review_decisions_thread_id",
        "review_decisions",
        ["thread_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # sync_runs — metadata for each Refresh Gmail invocation
    # ------------------------------------------------------------------
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("source", sa.String(32), nullable=False, server_default="anywhere"),
        sa.Column("fetched_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_thread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ------------------------------------------------------------------
    # runtime_settings — single-row mutable config (ai_mode, mailbox, etc.)
    # ------------------------------------------------------------------
    op.create_table(
        "runtime_settings",
        # id=1 is the only row; autoincrement=False enforces the singleton.
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("ai_mode", sa.String(32), nullable=False, server_default="openai"),
        sa.Column(
            "local_ai_force_all_threads",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("local_ai_model", sa.String(255), nullable=False, server_default=""),
        sa.Column("local_ai_agent_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("gmail_mailbox_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ------------------------------------------------------------------
    # contacts — auto-populated from sync, classified by domain
    # ------------------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column(
            "contact_type",
            sa.String(32),
            nullable=False,
            server_default="external",
        ),
        sa.Column("type_locked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("organization", sa.String(256), nullable=False, server_default=""),
        sa.Column("thread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contacts_email", "contacts", ["email"], unique=True)

    # ------------------------------------------------------------------
    # contact_threads — join table: contacts ↔ email_threads
    # ------------------------------------------------------------------
    op.create_table(
        "contact_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_thread_id", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="recipient"),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contact_threads_contact_id", "contact_threads", ["contact_id"])
    op.create_index(
        "ix_contact_threads_external_thread_id",
        "contact_threads",
        ["external_thread_id"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order (child / FK tables first).
    op.drop_table("contact_threads")
    op.drop_table("contacts")
    op.drop_table("runtime_settings")
    op.drop_table("sync_runs")
    op.drop_table("review_decisions")
    op.drop_table("drafts")
    op.drop_table("thread_states")
    op.drop_table("thread_analyses")
    op.drop_table("thread_messages")
    op.drop_table("email_threads")
