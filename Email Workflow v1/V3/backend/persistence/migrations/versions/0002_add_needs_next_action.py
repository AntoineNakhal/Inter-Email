"""Add explicit actionability flag to thread analyses.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("thread_analyses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "needs_next_action",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE thread_analyses
            SET needs_next_action = TRUE
            WHERE TRIM(COALESCE(next_action, '')) <> ''
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("thread_analyses") as batch_op:
        batch_op.drop_column("needs_next_action")
