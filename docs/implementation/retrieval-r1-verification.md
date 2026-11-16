# Verify R1 deterministic retrieval

R1 exposes independently ranked vector and lexical candidates. It does not fuse candidates, rerank,
generate an answer, or run an agent loop. Those remain R2–R4 work.

## What is implemented

- `knowledge_embeddings` denormalizes the immutable profile key and has a partial cosine HNSW
  expression index containing only the canonical 1,024-dimensional Qwen v1 vector space; other
  profiles coexist in the base table and require their own reviewed index.
- `knowledge_nodes.content` has both `simple` full-text and trigram GIN indexes. Trigram matching
  covers identifiers and text for which PostgreSQL's built-in tokenizer has weak segmentation.
- `RetrievalRepository` owns vector and lexical SQL. Every query filters workspace, allowed Teams,
  source lifecycle, optional Project/Issue scope, and the active embedding profile before returning
  content. Vector queries enable pgvector's strict-order iterative HNSW scan so profile and ACL
  filters cannot silently under-fill the requested candidate set after approximate index scanning.
- `RetrievalService` derives allowed Team IDs from the authenticated user. Request data can narrow
  this set but cannot expand it.
- `POST /api/v1/workspaces/{workspace_id}/retrieval/search` returns the two channels separately so
  their rankings remain inspectable before R2 fusion.

## Automated verification

From the repository root, using Python 3.12:

```bash
PYTHONPATH=backend python -m pytest backend/tests -q
```

With a migrated PostgreSQL/pgvector database:

```bash
TEST_DATABASE_URL=postgresql+psycopg://zhitong:zhitong@localhost:5432/zhitong \
PYTHONPATH=backend python -m pytest backend/tests/test_retrieval_postgres.py -q
```

Migration acceptance is upgrade, downgrade, and re-upgrade:

```bash
cd backend
alembic upgrade head
alembic downgrade 20261025_0022
alembic upgrade head
```

## API verification

Use a short-lived Business API bearer token belonging to a workspace member:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "TA-12 ONNX failure",
    "mode": "both",
    "limit": 10
  }' \
  "http://localhost:8000/api/v1/workspaces/${WORKSPACE_ID}/retrieval/search"
```

Expected response fields are `scope`, `embedding_profile_key`, `vector_results`, and
`lexical_results`. Each hit carries its source, scope, scores, page/heading provenance and stable
`citation_target`.

Repeat with `"mode": "vector"` and `"mode": "lexical"` to inspect each channel independently.
For a non-admin Team member, requesting a Team outside their membership must return HTTP 403 and the
repository must not run. A query for a deleted or non-ready source must never return that source.

## Database inspection

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname IN (
    'ix_knowledge_embeddings_hnsw_qwen_v1_cosine',
    'ix_knowledge_nodes_lexical_fts',
    'ix_knowledge_nodes_content_trgm'
)
ORDER BY indexname;
```

R1 quality evaluation should store a small set of queries with expected source/node IDs and report
Recall@5 and Recall@10. That fixture can grow without changing the repository contract; R2 will use
the same hits for RRF fusion, context expansion, and reranking.
