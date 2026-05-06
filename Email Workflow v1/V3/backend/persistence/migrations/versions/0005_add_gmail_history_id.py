"""Add gmail_history_id to runtime_settings.

Stores the Gmail users.history.list cursor per connected account.
Once populated, the sync service switches from full-window polling to
incremental history fetches, requesting only messages that changed since
the last run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gmail_history_id",
                sa.String(255),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.drop_column("gmail_history_id")
