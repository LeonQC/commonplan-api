"""replace placeholder embeddings with the canonical Qwen profile

Revision ID: 20261009_0020
Revises: 20261008_0019
"""

from alembic import op


revision = "20261009_0020"
down_revision = "20261008_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Embeddings are rebuildable derivative data. Values produced by the
        -- old placeholder profile cannot be cast into Qwen's vector space.
        DELETE FROM document_chunks;

        ALTER TABLE document_chunks DROP COLUMN embedding;
        ALTER TABLE document_chunks ADD COLUMN embedding vector(1024) NOT NULL;

        UPDATE document_ingestions
        SET status = 'pending',
            embedding_provider = 'tei',
            embedding_model = 'Qwen/Qwen3-Embedding-0.6B@97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3',
            embedding_dimensions = 1024,
            error_code = NULL,
            error_message = NULL,
            completed_at = NULL,
            updated_at = now()
        WHERE status <> 'deleted';

        INSERT INTO outbox_events (
            id, workspace_id, aggregate_type, aggregate_id, event_type,
            payload, status, attempts, available_at, created_at
        )
        SELECT
            substr(md5(random()::text || file.id || clock_timestamp()::text), 1, 8)
                || '-' || substr(md5(random()::text || file.id), 1, 4)
                || '-4' || substr(md5(random()::text), 1, 3)
                || '-a' || substr(md5(clock_timestamp()::text), 1, 3)
                || '-' || substr(md5(file.id || random()::text), 1, 12),
            file.workspace_id,
            'file_asset',
            file.id,
            'file.ready',
            jsonb_build_object('file_id', file.id, 'reason', 'embedding_profile_upgrade'),
            'pending',
            0,
            now(),
            now()
        FROM file_assets AS file
        JOIN document_ingestions AS ingestion ON ingestion.file_asset_id = file.id
        WHERE file.upload_status = 'ready'
          AND file.deleted_at IS NULL
          AND ingestion.status = 'pending'
          AND NOT EXISTS (
              SELECT 1
              FROM outbox_events AS existing
              WHERE existing.aggregate_id = file.id
                AND existing.event_type = 'file.ready'
                AND existing.status IN ('pending', 'processing')
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM document_chunks;

        ALTER TABLE document_chunks DROP COLUMN embedding;
        ALTER TABLE document_chunks ADD COLUMN embedding vector(384) NOT NULL;

        UPDATE document_ingestions
        SET status = 'failed',
            embedding_provider = 'local_hash',
            embedding_model = 'local-hash-v1',
            embedding_dimensions = 384,
            error_code = 'embedding_profile_downgraded',
            error_message = 'Re-ingestion is required after downgrading the embedding schema.',
            completed_at = now(),
            updated_at = now()
        WHERE status <> 'deleted';
        """
    )
