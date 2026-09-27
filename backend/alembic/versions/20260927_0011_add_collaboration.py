"""add collaboration

Revision ID: 20260927_0011
Revises: 20260921_0010
Create Date: 2026-09-27 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260927_0011"
down_revision: Union[str, None] = "20260921_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE issues
            ADD COLUMN parent_issue_id VARCHAR(36) NULL
                REFERENCES issues(id) ON DELETE SET NULL;
        CREATE INDEX ix_issues_parent ON issues (parent_issue_id);

        CREATE TABLE issue_watchers (
            issue_id VARCHAR(36) NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason VARCHAR(24) NOT NULL DEFAULT 'manual',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (issue_id, user_id)
        );
        CREATE INDEX ix_issue_watchers_user ON issue_watchers (user_id, created_at DESC);

        CREATE TABLE comment_mentions (
            comment_id VARCHAR(36) NOT NULL REFERENCES issue_comments(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (comment_id, user_id)
        );
        CREATE INDEX ix_comment_mentions_user ON comment_mentions (user_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE comment_mentions;
        DROP TABLE issue_watchers;
        DROP INDEX ix_issues_parent;
        ALTER TABLE issues DROP COLUMN parent_issue_id;
        """
    )
