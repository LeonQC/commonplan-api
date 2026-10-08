"""add durable document ingestion pipeline

Revision ID: 20261007_0018
Revises: 20261006_0017
"""

from alembic import op


revision = "20261007_0018"
down_revision = "20261006_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE outbox_events
            ADD COLUMN locked_at TIMESTAMPTZ,
            ADD COLUMN locked_by VARCHAR(120),
            ADD COLUMN last_error TEXT;

        CREATE TABLE document_ingestions (
            id VARCHAR(36) PRIMARY KEY,
            file_asset_id VARCHAR(36) NOT NULL UNIQUE REFERENCES file_assets(id) ON DELETE CASCADE,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            parser_name VARCHAR(80),
            parser_version VARCHAR(40),
            chunker_version VARCHAR(40) NOT NULL,
            embedding_provider VARCHAR(40) NOT NULL,
            embedding_model VARCHAR(120) NOT NULL,
            embedding_dimensions INTEGER NOT NULL,
            content_sha256 VARCHAR(64) NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            error_code VARCHAR(80),
            error_message TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_document_ingestion_status CHECK (
                status IN ('pending', 'parsing', 'chunking', 'embedding', 'ready', 'failed', 'deleted')
            ),
            CONSTRAINT ck_document_ingestion_attempts CHECK (attempts >= 0),
            CONSTRAINT ck_document_ingestion_dimensions CHECK (embedding_dimensions > 0)
        );
        CREATE INDEX ix_document_ingestions_file ON document_ingestions (file_asset_id);
        CREATE INDEX ix_document_ingestions_workspace ON document_ingestions (workspace_id);
        CREATE INDEX ix_document_ingestions_status ON document_ingestions (status);

        CREATE TABLE document_pages (
            id VARCHAR(36) PRIMARY KEY,
            ingestion_id VARCHAR(36) NOT NULL REFERENCES document_ingestions(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            heading_path TEXT,
            markdown_content TEXT NOT NULL,
            plain_text TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            CONSTRAINT uq_document_page_number UNIQUE (ingestion_id, page_number),
            CONSTRAINT ck_document_page_number CHECK (page_number > 0),
            CONSTRAINT ck_document_page_tokens CHECK (token_count >= 0)
        );
        CREATE INDEX ix_document_pages_ingestion ON document_pages (ingestion_id);

        CREATE TABLE document_chunks (
            id VARCHAR(36) PRIMARY KEY,
            ingestion_id VARCHAR(36) NOT NULL REFERENCES document_ingestions(id) ON DELETE CASCADE,
            parent_page_id VARCHAR(36) NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            team_id VARCHAR(36) NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            issue_id VARCHAR(36) REFERENCES issues(id) ON DELETE CASCADE,
            project_id VARCHAR(36) REFERENCES projects(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            token_count INTEGER NOT NULL,
            page_from INTEGER NOT NULL,
            page_to INTEGER NOT NULL,
            heading_path TEXT,
            embedding JSONB,
            chunk_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_document_chunk_index UNIQUE (ingestion_id, chunk_index),
            CONSTRAINT ck_document_chunk_scope CHECK (
                (issue_id IS NOT NULL AND project_id IS NULL)
                OR (issue_id IS NULL AND project_id IS NOT NULL)
            ),
            CONSTRAINT ck_document_chunk_index CHECK (chunk_index >= 0),
            CONSTRAINT ck_document_chunk_tokens CHECK (token_count > 0)
        );
        CREATE INDEX ix_document_chunks_ingestion ON document_chunks (ingestion_id);
        CREATE INDEX ix_document_chunks_parent ON document_chunks (parent_page_id);
        CREATE INDEX ix_document_chunks_scope ON document_chunks (workspace_id, team_id);
        CREATE INDEX ix_document_chunks_issue ON document_chunks (issue_id);
        CREATE INDEX ix_document_chunks_project ON document_chunks (project_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE document_chunks;
        DROP TABLE document_pages;
        DROP TABLE document_ingestions;
        ALTER TABLE outbox_events
            DROP COLUMN last_error,
            DROP COLUMN locked_by,
            DROP COLUMN locked_at;
        """
    )
