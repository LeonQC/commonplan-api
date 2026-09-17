"""link business profiles to the external auth service

Revision ID: 20260905_0004
Revises: 20260802_0003
Create Date: 2026-09-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260905_0004"
down_revision: Union[str, None] = "20260802_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN auth_issuer VARCHAR(255) NULL,
            ADD COLUMN auth_subject VARCHAR(255) NULL;

        CREATE UNIQUE INDEX ux_users_auth_identity
            ON users (auth_issuer, auth_subject)
            WHERE auth_subject IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX ux_users_auth_identity;
        ALTER TABLE users
            DROP COLUMN auth_subject,
            DROP COLUMN auth_issuer;
        """
    )
