"""Add password reset token columns to users.

Adds the two columns that back the local-account forgot-password flow:

- ``users.password_reset_token`` — one-time, single-use, ``secrets.token_urlsafe``
  generated value handed out by ``POST /auth/forgot-password`` and consumed by
  ``POST /auth/reset-password``. Unique-indexed so the reset endpoint can look
  the row up directly.
- ``users.password_reset_expires_at`` — timezone-aware deadline (default lifetime
  one hour from issuance). The endpoint refuses tokens past this point so
  forgotten links can't be replayed indefinitely.

Both columns are nullable — every user starts without a pending reset, and the
columns are cleared on successful use. This mirrors the existing
``password_setup_token`` pattern used for SSO invitations.

Revision ID: 090
Revises: 089
Create Date: 2026-05-18
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "090"
down_revision: Union[str, None] = "089"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_token", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_reset_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_password_reset_token",
        "users",
        ["password_reset_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_password_reset_token", table_name="users")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_token")
