"""Add is_service_email flag to email_threads.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS to safely handle the case where the
    # column was already added outside of a migration run.
    op.execute(
        "ALTER TABLE email_threads ADD COLUMN IF NOT EXISTS "
        "is_service_email BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    with op.batch_alter_table("email_threads") as batch_op:
        batch_op.drop_column("is_service_email")
