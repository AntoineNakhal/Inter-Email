"""Sync durability: persist progress + per-account run lock.

Adds two columns to sync_runs:
  - mailbox_account: the Gmail address that owns this run. Used to enforce
    a single-active-run-per-account constraint in application code.
  - progress_json: a JSON snapshot of the last-known SyncRunSummary fields
    (stage, progress_percent, stage_unit_current, stage_unit_total,
    status_message). Written at each stage transition so a process restart
    can surface the last meaningful state rather than a stale "running" row.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mailbox_account",
                sa.String(255),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "progress_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.drop_column("progress_json")
        batch_op.drop_column("mailbox_account")
