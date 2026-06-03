"""Add web_link column to thread_messages for provider deep-links.

Outlook messages store the webLink from Graph API so the frontend can
open the exact message in Outlook on the web without guessing the URL format.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_cols = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'thread_messages'"
            )
        )
    }
    if "web_link" not in existing_cols:
        op.add_column(
            "thread_messages",
            sa.Column("web_link", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("thread_messages", "web_link")
