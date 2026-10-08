"""add pgvector retrieval index

Revision ID: 20261008_0019
Revises: 20261007_0018
"""

from alembic import op


revision = "20261008_0019"
down_revision = "20261007_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS vector;

        ALTER TABLE document_chunks
            ADD COLUMN embedding_vector vector(384);

        UPDATE document_chunks
        SET embedding_vector = embedding::text::vector(384)
        WHERE embedding IS NOT NULL;

        ALTER TABLE document_chunks
            ALTER COLUMN embedding_vector SET NOT NULL;

        CREATE INDEX ix_document_chunks_embedding_hnsw
            ON document_chunks
            USING hnsw (embedding_vector vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX ix_document_chunks_embedding_hnsw;
        ALTER TABLE document_chunks DROP COLUMN embedding_vector;
        """
    )
