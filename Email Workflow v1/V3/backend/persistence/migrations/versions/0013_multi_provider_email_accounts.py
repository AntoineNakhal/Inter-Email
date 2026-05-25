"""Add email_accounts table and password_hash to users.

Separates authentication (email/password) from email provider connections.
One user can now connect multiple email accounts (Gmail, Outlook, iCloud,
IMAP) instead of being locked to a single Gmail OAuth identity.

Changes:
- users: ADD COLUMN password_hash TEXT (nullable — existing rows keep NULL)
- CREATE TABLE email_accounts

Existing gmail_token_encrypted on users is left in place for backwards
compatibility during a gradual rollout; it can be dropped in a future
migration once all data is migrated to email_accounts.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Add password_hash to users (if not already present)             #
    # ------------------------------------------------------------------ #
    conn = op.get_bind()
    existing_cols = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users'"
            )
        )
    }
    if "password_hash" not in existing_cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("password_hash", sa.Text(), nullable=True))

    # ------------------------------------------------------------------ #
    # 2. Create email_accounts table (if not already present)            #
    # ------------------------------------------------------------------ #
    existing_tables = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
    }
    if "email_accounts" in existing_tables:
        return

    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("email_address", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_email_accounts_user_id", "email_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_accounts_user_id", table_name="email_accounts")
    op.drop_table("email_accounts")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_hash")
