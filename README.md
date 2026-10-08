# CommonPlan API

The server platform for CommonPlan. This repository contains the Business API and Web BFF, the independent Auth Service, PostgreSQL migrations, Redis-backed application-session infrastructure, and the local Docker Compose stack.

## Service boundaries

- `backend/`: Business API and browser-facing BFF on port `8000`
- `auth_service/`: identity, Google OAuth, access-token signing, refresh-token rotation, and JWKS on port `8001`
- PostgreSQL: separate `zhitong` and `zhitong_auth` databases
- Redis: disposable cache for application sessions; it is not an authentication authority
- Attachment storage: a signed, persistent local file volume in development; private S3-compatible storage in deployment

Every business route is mounted behind the shared fail-closed access-token guard. The browser receives only an opaque HTTP-only BFF session cookie; access and refresh credentials remain server-managed.

## Local development

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Business API docs: <http://localhost:8000/docs>
- Auth Service docs: <http://localhost:8001/docs>
- Auth Service JWKS: <http://localhost:8001/.well-known/jwks.json>

Run the companion [`commonplan-web`](https://github.com/LeonQC/commonplan-web) repository at <http://localhost:5173>.

## GitHub pull-request linking

M7 links pull requests to issues when a PR title contains an exact item key. Local GitHub delivery requires a public forwarding URL; follow the [local GitHub webhook setup guide](docs/github-integration-local.md) for the smee daemon, environment variables, GitHub settings, and verification steps.

## Attachments

M9 stores attachment metadata and resource links in PostgreSQL while file bytes stay outside the database. Local Docker uses a persistent file volume behind signed Business API URLs; deployment can set `OBJECT_STORAGE_DRIVER=s3` to use a private S3-compatible bucket. The browser receives a short-lived upload URL, uploads directly, then calls the authenticated complete endpoint. Download URLs are also short lived and issued only after resource authorization is checked again. See [the attachment data/API contract](docs/data-model/07-attachments.md).

The KEY-11 ingestion foundation consumes those durable attachment events in a separate worker, preserving parent pages, retryable chunk/embedding state, resource ACL metadata, and canonical pgvector embeddings. Local Compose uses a deterministic embedding adapter so the complete flow works without an external API key. See [the ingestion design](docs/data-model/08-rag-ingestion.md) and [the ingestion verification runbook](docs/implementation/ingestion-verification.md).

## Tests

```bash
cd backend && pytest -q
cd ../auth_service && pytest -q
```

See [`docs/system-architecture.md`](docs/system-architecture.md) and [`docs/auth-service-plan.md`](docs/auth-service-plan.md) for the current architecture and authentication flows. Product data/API design starts at [`docs/data-model/README.md`](docs/data-model/README.md), and the staged implementation plan is in [`docs/implementation/milestones.md`](docs/implementation/milestones.md).
