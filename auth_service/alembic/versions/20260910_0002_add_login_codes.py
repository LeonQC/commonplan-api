"""add one-time login codes for the web BFF

Revision ID: 20260910_0002
Revises: 20260905_0001
Create Date: 2026-09-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260910_0002"
down_revision: Union[str, None] = "20260905_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE login_codes (
            code_hash VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES identity_users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_login_codes_user_id ON login_codes (user_id);
        CREATE INDEX ix_login_codes_expires_at ON login_codes (expires_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS login_codes;")
