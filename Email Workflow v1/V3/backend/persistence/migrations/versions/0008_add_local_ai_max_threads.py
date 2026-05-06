"""Add local_ai_max_threads to runtime_settings.

Defaults to 50 — when local or Claude AI mode is active, only the top 50
threads by relevance score are sent to AI. Set to 0 for unlimited.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "local_ai_max_threads",
                sa.Integer(),
                nullable=False,
                server_default="50",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.drop_column("local_ai_max_threads")
