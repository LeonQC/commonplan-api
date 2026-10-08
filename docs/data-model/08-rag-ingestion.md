# RAG ingestion foundation

This milestone turns a completed attachment into durable, access-scoped retrieval data without coupling upload availability to AI infrastructure.

## Runtime flow

```text
authenticated upload completion
  -> file_assets(upload_status=ready) + outbox_events(file.ready), one transaction
  -> ingestion-worker claims the event with FOR UPDATE SKIP LOCKED
  -> reads object storage and verifies SHA-256
  -> parser produces parent pages with page/heading metadata
  -> word-window chunker produces 300-token chunks with 50-token overlap
  -> embedding adapter produces vectors
  -> document_pages + document_chunks + document_ingestions(status=ready)
  -> outbox event becomes published
```

Upload completion returns before parsing or embeddings run. A failure is written to both the ingestion record and outbox event, then retried with exponential backoff. `locked_at` and `locked_by` form a lease, so another worker can recover an interrupted job. `file.deleted` removes pages and chunks and leaves a deleted ingestion tombstone.

## Tables

| Table | Responsibility |
| --- | --- |
| `outbox_events` | Durable queue, attempt count, lease owner, next retry, last error |
| `document_ingestions` | One current pipeline result per file, including checksum and parser/chunker/embedding versions |
| `document_pages` | Parent-page text used to expand the context around a matching chunk |
| `document_chunks` | Search units plus denormalized workspace/team/resource ACL scope and embedding |

Each chunk belongs to exactly one issue or project. The denormalized `workspace_id`, `team_id`, `issue_id`/`project_id` fields make it possible for the future retrieval query to apply authorization in the same database statement that selects candidates.

## Adapters and production evolution

The parser registry currently supports PDF, Markdown, plain text, CSV and JSON. Office files are accepted by upload but are intentionally reported as unsupported by ingestion until a structure-aware parser such as Docling is introduced.

`local_hash` is a deterministic, dependency-free adapter for local end-to-end testing; it is not semantic search. A deployment can set `INGESTION_EMBEDDING_PROVIDER=openai`, `INGESTION_EMBEDDING_MODEL=text-embedding-3-large`, and `OPENAI_API_KEY`. Embeddings are JSONB in this foundation so the pipeline does not require a database extension. M12 retrieval should migrate them to pgvector or a dedicated vector index before similarity search is shipped.

## API and operation

- `GET /api/v1/workspaces/{workspace_id}/files/{file_id}/ingestion` returns `not_started`, current stage, counts, adapter versions, or failure details after normal resource authorization.
- `python -m app.ingestion.worker` runs continuously.
- `python -m app.ingestion.worker --once` claims at most one event for deterministic local verification.
- Docker Compose starts `ingestion-worker` against the same database and attachment volume as the Business API.

The service layer never receives a SQLAlchemy session. All claims, reads, writes, retries and counts stay inside `IngestionRepository`.
