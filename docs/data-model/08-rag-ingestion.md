# RAG ingestion foundation

This milestone turns a completed attachment into durable, access-scoped retrieval data without coupling upload availability to AI infrastructure.

## Runtime flow

```text
authenticated upload completion
  -> file_assets(upload_status=ready) + outbox_events(file.ready), one transaction
  -> ingestion-worker claims the event with FOR UPDATE SKIP LOCKED
  -> reads object storage and verifies SHA-256
  -> Docling parses layout, reading order, tables, OCR, pages, and headings
  -> Docling HybridChunker uses the pinned Qwen tokenizer (300-token maximum)
  -> private TEI service produces normalized 1024-dimensional Qwen vectors
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
| `document_chunks` | Search units plus denormalized workspace/team/resource ACL scope and canonical `vector(1024)` embedding |

Each chunk belongs to exactly one issue or project. The denormalized `workspace_id`, `team_id`, `issue_id`/`project_id` fields make it possible for the future retrieval query to apply authorization in the same database statement that selects candidates.

## Adapters and production evolution

Docling 2.135.0 handles PDF, CSV, DOCX, XLSX, PPTX, and supported images in the dedicated worker image. It preserves structured Markdown, per-page provenance, headings, reading order, and tables. Plain text, Markdown, and JSON retain a lightweight parser because their source representation is already canonical. Legacy binary `.doc` uploads remain downloadable but are not ingestible; callers receive `unsupported_content_type` instead of a misleading partial parse.

### Chunk overlap policy

The two chunking paths do not currently have identical overlap behavior:

- Plain-text fallback chunks use a 300-word sliding window with 50 words of overlap.
- Docling documents use structure-aware `HybridChunker` output without synthetic overlap. The
  current Docling API splits oversized structural units and merges compatible peers, but does not
  expose a `chunk_overlap` option.

CommonPlan must not add hidden overlap only to the text sent to the embedding model. Doing so would
make the persisted chunk text differ from the content represented by its vector, obscure provenance,
and make re-indexing and retrieval debugging harder. The canonical rule is that the contextualized
text persisted for a chunk is the same text used to create its embedding.

The first retrieval implementation should expand a hit with its parent page or explicitly selected
neighbor chunks, then rerank and deduplicate that context. This recovers boundary context without
duplicating every structure-aware chunk in the index. If the retrieval regression dataset later shows
a measurable boundary-recall problem, overlap may be introduced as a versioned chunker change only
when all of the following are stored explicitly: the overlapped canonical text, source chunk/span IDs,
the union of source-page provenance, and the new chunker version. Search must then collapse duplicate
neighbor hits before assembling context. A cross-heading, cross-table, or cross-resource overlap is
never permitted.

The canonical embedding profile is `Qwen/Qwen3-Embedding-0.6B` at revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, served privately by TEI 1.9. The worker sends bounded batches, validates the response count and dimensions, rejects zero/non-finite vectors, normalizes defensively, and persists `vector(1024)`. Model ID, immutable revision, and dimensions are part of the durable ingestion identity. Local CPU defaults use three chunks per client batch and a 1,024-token scheduler budget because CommonPlan chunks are capped at 300 tokens; GPU deployments can raise both through environment variables. `local_hash` remains available only when explicitly selected for isolated tests; the factory never silently falls back to it.

The model weights and Docling assets use persistent Docker volumes. After the first successful download, restarts do not fetch them again. ARM64 local development uses TEI's `cpu-arm64-1.9` image; x86_64 deployments must set `TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`.

Embedding changes are intentionally migration-controlled. Migration `20261009_0020` discards old vectors because they are derived data in an incompatible vector space, changes the column to `vector(1024)`, and queues every ready source file for re-ingestion. Source objects and authorization metadata remain authoritative.

This phase intentionally creates no vector similarity index and exposes no similarity-search API. HNSW/index tuning, authorization-filtered candidate selection, reranking and citations belong to the separately reviewed retrieval phase.

## API and operation

- `GET /api/v1/workspaces/{workspace_id}/files/{file_id}/ingestion` returns `not_started`, current stage, counts, adapter versions, or failure details after normal resource authorization.
- `python -m app.ingestion.worker` runs continuously.
- `python -m app.ingestion.worker --once` claims at most one event for deterministic local verification.
- Docker Compose starts `embedding-service` and the heavier `ingestion-worker` image separately from the Business API. Docling dependencies never enter the latency-sensitive API image.
- [`../implementation/ingestion-verification.md`](../implementation/ingestion-verification.md) provides the upload, status, SQL inspection, invariant, and recovery checks used to accept this phase before retrieval begins.

The service layer never receives a SQLAlchemy session. All claims, reads, writes, retries and counts stay inside `IngestionRepository`.
