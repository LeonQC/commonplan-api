"""add GitHub pull-request integration

Revision ID: 20260928_0013
Revises: 20260927_0012
Create Date: 2026-09-28 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260928_0013"
down_revision: Union[str, None] = "20260927_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE github_pull_requests (
            id VARCHAR(36) PRIMARY KEY,
            github_repo_id BIGINT NOT NULL,
            github_repo_full_name VARCHAR(255) NOT NULL,
            pr_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            html_url TEXT NOT NULL,
            state VARCHAR(16) NOT NULL CHECK (state IN ('open', 'closed', 'merged')),
            is_draft BOOLEAN NOT NULL DEFAULT false,
            merged_at TIMESTAMPTZ NULL,
            github_updated_at TIMESTAMPTZ NOT NULL,
            last_received_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_github_pull_request UNIQUE (github_repo_id, pr_number)
        );
        CREATE INDEX ix_github_pull_requests_repo ON github_pull_requests (github_repo_id);

        CREATE TABLE issue_pr_links (
            issue_id VARCHAR(36) NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            pull_request_id VARCHAR(36) NOT NULL REFERENCES github_pull_requests(id) ON DELETE CASCADE,
            source VARCHAR(24) NOT NULL DEFAULT 'title_key',
            linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            detached_at TIMESTAMPTZ NULL,
            PRIMARY KEY (issue_id, pull_request_id),
            CONSTRAINT ck_issue_pr_links_source CHECK (source IN ('title_key'))
        );
        CREATE INDEX ix_issue_pr_links_active
            ON issue_pr_links (issue_id, detached_at);

        CREATE TABLE github_webhook_deliveries (
            delivery_id VARCHAR(36) PRIMARY KEY,
            github_repo_id BIGINT NULL,
            event_type VARCHAR(40) NOT NULL,
            action VARCHAR(40) NULL,
            status VARCHAR(16) NOT NULL
                CHECK (status IN ('pending', 'processed', 'failed', 'ignored')),
            received_at TIMESTAMPTZ NOT NULL,
            processed_at TIMESTAMPTZ NULL,
            error_code VARCHAR(80) NULL
        );
        CREATE INDEX ix_github_webhook_deliveries_repo
            ON github_webhook_deliveries (github_repo_id, received_at DESC);
        CREATE INDEX ix_github_webhook_deliveries_received
            ON github_webhook_deliveries (received_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE github_webhook_deliveries;
        DROP TABLE issue_pr_links;
        DROP TABLE github_pull_requests;
        """
    )
