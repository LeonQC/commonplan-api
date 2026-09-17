"""add password hash

Revision ID: 20260801_0002
Revises: 20260723_0001
Create Date: 2026-08-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0002"
down_revision: Union[str, None] = "20260723_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=512), nullable=True),
    )
    op.execute("UPDATE users SET email = lower(email)")
    op.create_index(
        "ux_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_users_email_lower", table_name="users")
    op.drop_column("users", "password_hash")
