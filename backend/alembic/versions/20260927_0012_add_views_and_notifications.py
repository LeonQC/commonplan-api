"""add saved views and notifications

Revision ID: 20260927_0012
Revises: 20260927_0011
Create Date: 2026-09-27 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260927_0012"
down_revision: Union[str, None] = "20260927_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE saved_views (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            team_id VARCHAR(36) NULL REFERENCES teams(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            visibility VARCHAR(16) NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('private', 'team', 'workspace')),
            filter_version SMALLINT NOT NULL DEFAULT 1,
            filter_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
            group_by VARCHAR(24) NULL,
            sort_by VARCHAR(32) NOT NULL DEFAULT 'updated_at',
            sort_direction VARCHAR(4) NOT NULL DEFAULT 'desc'
                CHECK (sort_direction IN ('asc', 'desc')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at TIMESTAMPTZ NULL
        );
        CREATE INDEX ix_saved_views_workspace ON saved_views (workspace_id, archived_at);
        CREATE INDEX ix_saved_views_team ON saved_views (team_id, visibility);
        CREATE INDEX ix_saved_views_owner ON saved_views (owner_user_id, archived_at);

        CREATE TABLE notifications (
            id VARCHAR(36) PRIMARY KEY,
            recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            issue_id VARCHAR(36) NULL REFERENCES issues(id) ON DELETE CASCADE,
            issue_event_id VARCHAR(36) NULL REFERENCES issue_events(id) ON DELETE SET NULL,
            actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            kind VARCHAR(48) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            dedupe_key VARCHAR(160) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at TIMESTAMPTZ NULL
        );
        CREATE INDEX ix_notifications_recipient_created
            ON notifications (recipient_user_id, created_at DESC, id);
        CREATE INDEX ix_notifications_recipient_unread
            ON notifications (recipient_user_id, read_at) WHERE read_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE notifications;
        DROP TABLE saved_views;
        """
    )
