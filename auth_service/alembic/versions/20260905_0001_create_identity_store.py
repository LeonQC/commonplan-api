"""create independent identity store

Revision ID: 20260905_0001
Revises:
Create Date: 2026-09-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260905_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE identity_users (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            name VARCHAR(255) NOT NULL,
            password_hash VARCHAR(512) NULL,
            avatar_url VARCHAR(1024) NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX ux_identity_users_email_lower
            ON identity_users (lower(email));

        CREATE TABLE external_identities (
            id SERIAL PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            user_id VARCHAR(36) NOT NULL
                REFERENCES identity_users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (provider, subject)
        );

        CREATE INDEX ix_external_identities_provider
            ON external_identities (provider);
        CREATE INDEX ix_external_identities_subject
            ON external_identities (subject);
        CREATE INDEX ix_external_identities_user_id
            ON external_identities (user_id);

        CREATE TABLE refresh_tokens (
            id SERIAL PRIMARY KEY,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            family_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL
                REFERENCES identity_users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            replaced_by_hash VARCHAR(64) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
        CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
        CREATE INDEX ix_refresh_tokens_expires_at ON refresh_tokens (expires_at);

        CREATE TABLE login_attempts (
            identifier_hash VARCHAR(64) PRIMARY KEY,
            failed_attempts INTEGER NOT NULL,
            window_started_at TIMESTAMPTZ NOT NULL,
            locked_until TIMESTAMPTZ NULL
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS login_attempts;
        DROP TABLE IF EXISTS refresh_tokens;
        DROP TABLE IF EXISTS external_identities;
        DROP TABLE IF EXISTS identity_users;
        """
    )
