"""store document chunk embeddings as pgvector

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
            ALTER COLUMN embedding TYPE vector(384)
            USING embedding::text::vector(384),
            ALTER COLUMN embedding SET NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_chunks
            ALTER COLUMN embedding DROP NOT NULL,
            ALTER COLUMN embedding TYPE jsonb
            USING embedding::text::jsonb;
        """
    )
