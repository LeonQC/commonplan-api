"""add authorization-scoped lexical and vector retrieval indexes

Revision ID: 20261114_0023
Revises: 20261025_0022
"""

from alembic import op


revision = "20261114_0023"
down_revision = "20261025_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE knowledge_embeddings
            ADD COLUMN embedding_profile_key varchar(240);
        UPDATE knowledge_embeddings AS embedding
        SET embedding_profile_key = profile.profile_key
        FROM embedding_profiles AS profile
        WHERE profile.id = embedding.embedding_profile_id;
        ALTER TABLE knowledge_embeddings
            ALTER COLUMN embedding_profile_key SET NOT NULL,
            ADD CONSTRAINT fk_knowledge_embedding_profile_key
                FOREIGN KEY (embedding_profile_key)
                REFERENCES embedding_profiles(profile_key);
        CREATE INDEX ix_knowledge_embeddings_profile_key
            ON knowledge_embeddings (embedding_profile_key);

        CREATE INDEX ix_knowledge_nodes_lexical_fts
            ON knowledge_nodes
            USING gin (to_tsvector('simple', content))
            WHERE indexable = true;

        CREATE INDEX ix_knowledge_nodes_content_trgm
            ON knowledge_nodes
            USING gin (content gin_trgm_ops)
            WHERE indexable = true;

        -- The index contains one immutable vector space only. New embedding
        -- profiles coexist in the table and receive their own reviewed index.
        CREATE INDEX ix_knowledge_embeddings_hnsw_qwen_v1_cosine
            ON knowledge_embeddings
            USING hnsw ((embedding::vector(1024)) vector_cosine_ops)
            WHERE vector_dims(embedding) = 1024
              AND embedding_profile_key =
                'model_gateway:commonplan-embedding-v1:Qwen/Qwen3-Embedding-0.6B@97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3:1024';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_knowledge_embeddings_hnsw_qwen_v1_cosine;
        DROP INDEX IF EXISTS ix_knowledge_nodes_content_trgm;
        DROP INDEX IF EXISTS ix_knowledge_nodes_lexical_fts;
        DROP INDEX IF EXISTS ix_knowledge_embeddings_profile_key;
        ALTER TABLE knowledge_embeddings
            DROP CONSTRAINT IF EXISTS fk_knowledge_embedding_profile_key,
            DROP COLUMN IF EXISTS embedding_profile_key;
        -- pg_trgm may be shared by other application indexes, so downgrade does
        -- not remove the extension itself.
        """
    )
