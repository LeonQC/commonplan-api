"""add refresh tokens and durable application sessions

Revision ID: 20260802_0003
Revises: 20260801_0002
Create Date: 2026-08-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260802_0003"
down_revision: Union[str, None] = "20260801_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id SERIAL PRIMARY KEY,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            family_id VARCHAR(36) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            replaced_by_hash VARCHAR(64) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
        CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
        CREATE INDEX ix_refresh_tokens_expires_at ON refresh_tokens (expires_at);

        CREATE TABLE application_sessions (
            id SERIAL PRIMARY KEY,
            session_hash VARCHAR(64) NOT NULL UNIQUE,
            user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_application_sessions_user_id ON application_sessions (user_id);
        CREATE INDEX ix_application_sessions_expires_at ON application_sessions (expires_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE application_sessions;
        DROP TABLE refresh_tokens;
        """
    )
