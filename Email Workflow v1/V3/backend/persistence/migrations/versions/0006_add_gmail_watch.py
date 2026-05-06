"""Add Gmail push-notification watch state to runtime_settings.

Tracks the active Pub/Sub watch for the connected Gmail account:
  - gmail_watch_resource_id: the opaque ID returned by users.watch() —
    needed to call users.stop() when reconnecting or switching accounts.
  - gmail_watch_expiry: UTC timestamp when the current watch expires
    (Gmail guarantees at most 7 days). The sync service renews the watch
    before this deadline.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gmail_watch_resource_id",
                sa.String(255),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gmail_watch_expiry",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.drop_column("gmail_watch_expiry")
        batch_op.drop_column("gmail_watch_resource_id")
