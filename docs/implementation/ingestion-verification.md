# Verify document ingestion before retrieval

This runbook deliberately stops before similarity search. Its acceptance
boundary is: a completed attachment is parsed, chunked, embedded, and stored as
authorized `vector(384)` rows that can be inspected independently of any
retrieval or answer-generation behavior.

## 1. Start the ingestion stack

```bash
docker compose up --build db redis auth-service backend ingestion-worker
```

The database image includes pgvector. Alembic enables the extension and changes
`document_chunks.embedding` from the temporary JSONB representation to the
canonical `vector(384)` type.

## 2. Produce one ingestion

Open the web application, enter an Issue or Project detail page, and upload a
small Markdown, text, PDF, CSV, or JSON file. Upload completion writes the ready
file and its `file.ready` outbox event in one transaction. The worker handles
parsing and embeddings asynchronously.

The authenticated status endpoint is:

```text
GET /api/v1/workspaces/{workspace_id}/files/{file_id}/ingestion
```

The expected terminal response has `status: "ready"`, non-zero `page_count` and
`chunk_count`, the configured embedding provider/model, and no error fields.

## 3. Inspect the durable result with SQL

Run the repository's read-only inspection queries:

```bash
docker compose exec -T db psql -U zhitong -d zhitong \
  < docs/implementation/verify-ingestion.sql
```

For a successful upload, verify:

- `file_assets.upload_status = 'ready'`;
- `document_ingestions.status = 'ready'`;
- page and chunk counts are greater than zero;
- every chunk reports `vector_dims = 384` and a non-zero `vector_norm`;
- `workspace_id`, `team_id`, and exactly one resource ID are present;
- the acceptance-invariant query returns zero rows;
- no corresponding outbox event remains pending or failed.

To inspect one file, copy its `file_id` from the first result and add
`WHERE i.file_asset_id = '<file-id>'` to the second query. The third query shows
the actual chunk text, page/heading metadata, ACL scope, and vector facts without
performing nearest-neighbor search.

## 4. Exercise failure and recovery

Upload an unsupported Office file to confirm that the ingestion becomes
`failed` while the original attachment remains downloadable. Its error code and
message should appear in both the status endpoint and inspection query.

After fixing a transient worker/configuration problem, set the failed event back
to `pending` only in a disposable local database, or upload the file again. The
worker's lease, attempt count, and exponential backoff are visible in
`outbox_events`; process restart must not lose the job.

## What this does not validate

The local `local_hash` adapter is deterministic and useful for verifying the
pipeline, storage shape, and idempotency, but it is not evidence of semantic
quality. Retrieval evaluation starts only after this ingestion contract is
accepted. That later phase will add the vector index, authorization-filtered
nearest-neighbor query, reranking, citations, and quality fixtures.
