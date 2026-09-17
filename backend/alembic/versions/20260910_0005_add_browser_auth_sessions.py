"""add server-side browser auth session vault

Revision ID: 20260910_0005
Revises: 20260905_0004
Create Date: 2026-09-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260910_0005"
down_revision: Union[str, None] = "20260905_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE browser_auth_sessions (
            session_hash VARCHAR(64) PRIMARY KEY,
            auth_subject VARCHAR(36) NOT NULL,
            encrypted_refresh_token VARCHAR(1024) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_browser_auth_sessions_auth_subject
            ON browser_auth_sessions (auth_subject);
        CREATE INDEX ix_browser_auth_sessions_expires_at
            ON browser_auth_sessions (expires_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS browser_auth_sessions;")
