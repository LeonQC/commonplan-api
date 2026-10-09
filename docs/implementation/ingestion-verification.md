# Verify document ingestion before retrieval

This runbook deliberately stops before similarity search. Its acceptance
boundary is: a completed attachment is parsed, chunked, embedded, and stored as
authorized `vector(1024)` rows that can be inspected independently of any
retrieval or answer-generation behavior.

## 1. Start the ingestion stack

```bash
docker compose up --build db redis auth-service embedding-service backend ingestion-worker
```

The database image includes pgvector. Alembic enables the extension and changes
`document_chunks.embedding` from the temporary JSONB representation to the
canonical `vector(1024)` type. The first start downloads the pinned Qwen model
and Docling assets into persistent volumes. Wait for the TEI health endpoint:

```bash
curl --fail http://localhost:8080/health
```

The local embedding endpoint is bound to `127.0.0.1` only. The conservative CPU defaults (`3` inputs and `1,024` scheduled tokens per batch) keep Qwen warm-up practical on a development laptop; tune `INGESTION_EMBEDDING_BATCH_SIZE`, `TEI_MAX_BATCH_TOKENS`, `TEI_MAX_CONCURRENT_REQUESTS`, and `TEI_TOKENIZATION_WORKERS` for a GPU deployment.

Apple Silicon uses the default ARM64 image. On x86_64 set:

```bash
TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 docker compose up --build
```

## 2. Produce one ingestion

Open the web application, enter an Issue or Project detail page, and upload a
small Markdown, text, PDF, CSV, JSON, DOCX, XLSX, PPTX, or image file. Upload completion writes the ready
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
- every chunk reports `vector_dims = 1024` and `vector_norm` close to `1.0`;
- structured formats report `parser_name = 'docling'` and `chunk_metadata.strategy = 'docling_hybrid'`;
- `workspace_id`, `team_id`, and exactly one resource ID are present;
- the acceptance-invariant query returns zero rows;
- no corresponding outbox event remains pending or failed.

To inspect one file, copy its `file_id` from the first result and add
`WHERE i.file_asset_id = '<file-id>'` to the second query. The third query shows
the actual chunk text, page/heading metadata, ACL scope, and vector facts without
performing nearest-neighbor search.

## 4. Exercise failure and recovery

Upload a legacy binary `.doc` file to confirm that the ingestion becomes
`failed` while the original attachment remains downloadable. Its error code and
message should appear in both the status endpoint and inspection query.

After fixing a transient worker/configuration problem, set the failed event back
to `pending` only in a disposable local database, or upload the file again. The
worker's lease, attempt count, and exponential backoff are visible in
`outbox_events`; process restart must not lose the job.

## 5. Verify the embedding service directly

```bash
curl http://localhost:8080/embed \
  -H 'Content-Type: application/json' \
  -d '{"inputs":["CommonPlan links issues to project knowledge."],"normalize":true}' \
  | python -c 'import json,sys; v=json.load(sys.stdin)[0]; print(len(v), round(sum(x*x for x in v), 6))'
```

Expected output is `1024 1.0` (subject only to floating-point rounding).

## What this does not validate

This proves that production parsing and semantic vectors are durable. It does
not prove retrieval quality. The later retrieval phase will add the vector
index, authorization-filtered nearest-neighbor query, lexical search, fusion,
reranking, citations, and a bilingual quality regression dataset.
