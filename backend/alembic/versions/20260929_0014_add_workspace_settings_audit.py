"""add workspace settings and audit events

Revision ID: 20260929_0014
Revises: 20260928_0013
"""

from alembic import op


revision = "20260929_0014"
down_revision = "20260928_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workspace_settings (
            workspace_id VARCHAR(36) PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
            allow_member_invites BOOLEAN NOT NULL DEFAULT FALSE,
            default_timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
            domain_policy VARCHAR(24) NOT NULL DEFAULT 'invite_only',
            updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_workspace_settings_domain_policy
                CHECK (domain_policy IN ('invite_only', 'verified_domains'))
        );
        """
    )
    op.execute(
        """
        INSERT INTO workspace_settings (workspace_id)
        SELECT id FROM workspaces;
        """
    )
    op.execute(
        """
        CREATE TABLE audit_events (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(120) NOT NULL,
            target_type VARCHAR(64) NOT NULL,
            target_id VARCHAR(255),
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_events_workspace_id ON audit_events(workspace_id);
        CREATE INDEX ix_audit_events_actor_user_id ON audit_events(actor_user_id);
        CREATE INDEX ix_audit_events_action ON audit_events(action);
        CREATE INDEX ix_audit_events_created_at ON audit_events(created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events;")
    op.execute("DROP TABLE workspace_settings;")
