"""Add gmail_mailbox_name to runtime_settings.

This column stores the display name pulled from the Gmail sendAs profile
(e.g. "Antoine Nakhal") so draft generation never infers the sender's name
from the email address prefix.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gmail_mailbox_name",
                sa.String(255),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("runtime_settings") as batch_op:
        batch_op.drop_column("gmail_mailbox_name")
