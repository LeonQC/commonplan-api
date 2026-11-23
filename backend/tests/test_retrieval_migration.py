from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261114_0023_add_retrieval_indexes.py"
)


def test_retrieval_migration_has_vector_and_bilingual_lexical_indexes():
    source = MIGRATION.read_text()

    assert "USING hnsw" in source
    assert "embedding::vector(1024)" in source
    assert "vector_cosine_ops" in source
    assert "vector_dims(embedding) = 1024" in source
    assert "embedding_profile_key =" in source
    assert "commonplan-embedding-v1:Qwen/Qwen3-Embedding-0.6B@" in source
    assert "to_tsvector('simple', content)" in source
    assert "gin_trgm_ops" in source


def test_retrieval_migration_downgrade_removes_every_created_index():
    source = MIGRATION.read_text()

    for name in (
        "ix_knowledge_embeddings_hnsw_qwen_v1_cosine",
        "ix_knowledge_nodes_content_trgm",
        "ix_knowledge_nodes_lexical_fts",
        "ix_knowledge_embeddings_profile_key",
    ):
        assert f"DROP INDEX IF EXISTS {name}" in source
