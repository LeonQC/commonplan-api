"""add file assets, resource links, and durable outbox

Revision ID: 20261006_0017
Revises: 20260930_0016
"""

from alembic import op


revision = "20261006_0017"
down_revision = "20260930_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE file_assets (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            original_filename VARCHAR(255) NOT NULL,
            storage_key VARCHAR(768) NOT NULL UNIQUE,
            content_type VARCHAR(255) NOT NULL,
            byte_size BIGINT NOT NULL,
            sha256 VARCHAR(64),
            upload_status VARCHAR(24) NOT NULL DEFAULT 'pending',
            scan_status VARCHAR(24) NOT NULL DEFAULT 'not_configured',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ready_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_file_asset_size CHECK (byte_size > 0),
            CONSTRAINT ck_file_asset_upload_status CHECK (upload_status IN ('pending', 'ready', 'deleted', 'failed')),
            CONSTRAINT ck_file_asset_scan_status CHECK (scan_status IN ('not_configured', 'pending', 'clean', 'rejected'))
        );
        CREATE INDEX ix_file_assets_workspace ON file_assets (workspace_id);
        CREATE INDEX ix_file_assets_uploader ON file_assets (uploaded_by_user_id);
        CREATE INDEX ix_file_assets_status ON file_assets (upload_status);

        CREATE TABLE issue_attachments (
            issue_id VARCHAR(36) NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            file_asset_id VARCHAR(36) NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            added_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (issue_id, file_asset_id),
            CONSTRAINT uq_issue_attachment_file UNIQUE (file_asset_id)
        );
        CREATE INDEX ix_issue_attachments_issue ON issue_attachments (issue_id);

        CREATE TABLE project_attachments (
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            file_asset_id VARCHAR(36) NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
            added_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, file_asset_id),
            CONSTRAINT uq_project_attachment_file UNIQUE (file_asset_id)
        );
        CREATE INDEX ix_project_attachments_project ON project_attachments (project_id);

        CREATE TABLE outbox_events (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            aggregate_type VARCHAR(64) NOT NULL,
            aggregate_id VARCHAR(36) NOT NULL,
            event_type VARCHAR(120) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ,
            CONSTRAINT ck_outbox_status CHECK (status IN ('pending', 'processing', 'published', 'failed')),
            CONSTRAINT ck_outbox_attempts CHECK (attempts >= 0)
        );
        CREATE INDEX ix_outbox_workspace ON outbox_events (workspace_id);
        CREATE INDEX ix_outbox_aggregate ON outbox_events (aggregate_id);
        CREATE INDEX ix_outbox_event_type ON outbox_events (event_type);
        CREATE INDEX ix_outbox_pending ON outbox_events (status, available_at, created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE outbox_events;
        DROP TABLE project_attachments;
        DROP TABLE issue_attachments;
        DROP TABLE file_assets;
        """
    )
