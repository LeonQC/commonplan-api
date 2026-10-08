# Authorization-scoped RAG retrieval

This slice turns ready document chunks into a caller-scoped retrieval API. It does not generate an LLM answer; it returns ranked evidence and citations that a later answer service or agent can consume.

## Request flow

```text
authenticated caller
  -> RetrievalService resolves caller's allowed teams
  -> RetrievalOperator embeds the query
  -> RetrievalRepository executes pgvector search with ACL predicates
  -> candidate chunks are reranked with vector + lexical evidence
  -> parent-page context and stable citation metadata are returned
```

Authorization is applied inside the nearest-neighbor SQL statement using `workspace_id` and the caller's allowed `team_id` values. Optional team, issue, and project filters can only narrow that set. The repository also requires the chunk's ingestion provider/model to match the query embedding provider/model, preventing comparisons between incompatible vector spaces. HNSW iterative scanning is enabled per transaction so post-index ACL filters do not silently reduce recall.

## Storage and index

Migration `20261008_0019` installs pgvector, backfills `vector(384)` from the ingestion JSONB portability column, makes the vector non-null, and builds an HNSW cosine index. Local Compose uses the version-pinned `pgvector/pgvector:0.8.7-pg16` image. Changing embedding dimensions requires a deliberate migration because the database column has a fixed dimension.

## Endpoint

`POST /api/v1/workspaces/{workspace_id}/retrieval/search`

```json
{
  "query": "How are refresh tokens rotated?",
  "limit": 10,
  "team_id": null,
  "issue_key": null,
  "project_id": null
}
```

Each result includes the matching excerpt, expanded parent-page context, component scores, and a citation containing filename, page, heading, team, file ID, and issue/project identity.

The local hash adapter makes the full query path deterministic but mostly lexical. Configure the same semantic embedding provider/model for both ingestion-worker and backend in deployment. Reranking is currently a deterministic vector/lexical blend; a cross-encoder can replace it behind the operator without exposing database access to the service layer.
