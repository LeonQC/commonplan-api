# GitHub pull-request integration: local setup

M7 uses a signed repository or organization webhook. It does **not** use GitHub OAuth, a GitHub App, or a project-to-repository mapping. A pull request links to every existing CommonPlan issue key found exactly in its title, for example `KEY-12 Add GitHub integration`.

## Why localhost needs a forwarding daemon

GitHub cannot use `localhost` or `127.0.0.1` as a webhook payload URL. For local development, GitHub's documentation uses [smee.io as a public webhook proxy](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/testing-webhooks) and a local `smee-client` process to forward deliveries to the API. The daemon is required only while testing against a local API. A deployed API with a public HTTPS endpoint does not need it.

The proxy must preserve the raw request body and GitHub headers because CommonPlan validates `X-Hub-Signature-256` exactly as described by GitHub's [webhook signature guide](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

## 1. Choose the CommonPlan workspace and GitHub owner

Get the workspace ID from the local database:

```bash
docker exec project-zhitong-1-db-1 psql -U zhitong -d zhitong \
  -c 'SELECT id, name, slug FROM workspaces ORDER BY created_at;'
```

Get the numeric GitHub owner ID. `LeonQC` is the owner login in this example:

```bash
curl --fail --silent https://api.github.com/users/LeonQC
```

Use the response's numeric `id`, not the login name, as the allowlist boundary. Repository webhooks from either an organization or a personal account expose this value as `repository.owner.id`.

## 2. Generate and configure the shared secret

Generate a new development secret locally:

```bash
openssl rand -hex 32
```

Add these values to the API repository's root `.env` file. Do not commit the file or paste the secret into an issue or PR.

```dotenv
GITHUB_WEBHOOK_SECRET=<generated value>
GITHUB_ALLOWED_OWNER_ID=<numeric owner id>
GITHUB_ALLOWED_OWNER_LOGIN=LeonQC
GITHUB_WORKSPACE_ID=<CommonPlan workspace UUID>
GITHUB_HOOK_ID=
```

`GITHUB_HOOK_ID` is optional for the initial ping. After GitHub creates the webhook, its numeric ID can be copied from the webhook settings URL and added for a second source check.

Restart the API after changing the environment:

```bash
docker compose up -d --build backend-migrate backend
```

## 3. Create the public proxy URL

1. Open [smee.io](https://smee.io/) and choose **Start a new channel**.
2. Copy the generated `https://smee.io/...` URL. Treat it as temporary development infrastructure; do not use a public smee channel for production data.
3. Keep this local forwarding process running in its own terminal:

```bash
pnpm dlx smee-client \
  --url https://smee.io/YOUR_CHANNEL \
  --target http://localhost:8000/webhooks/github
```

The client should report that the public channel is forwarding to `http://localhost:8000/webhooks/github`. Stopping the process stops local delivery; it does not remove the GitHub webhook.

## 4. Add the GitHub webhook

In each repository that should participate:

1. Open **Settings → Webhooks → Add webhook**.
2. Set **Payload URL** to the smee channel URL—not the localhost target.
3. Set **Content type** to `application/json`.
4. Set **Secret** to the exact `GITHUB_WEBHOOK_SECRET` value.
5. Choose **Let me select individual events** and enable only **Pull requests**.
6. Leave **Active** enabled and add the webhook.

GitHub sends a `ping` immediately. The CommonPlan endpoint also accepts the relevant `pull_request` actions. See GitHub's [webhook creation instructions](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks).

## 5. Verify end to end

1. In CommonPlan, open **Settings → Applications → GitHub**. The integration should show **Connected** and the ping as the latest delivery.
2. Create or edit a PR title so it contains an existing item key exactly, such as `KEY-1 Verify GitHub linking`.
3. Open that issue in CommonPlan. The PR appears under **Development → Pull requests**.
4. Edit the PR title to remove the key. The link disappears after the next webhook delivery.
5. In GitHub's webhook **Recent Deliveries**, redeliver the same event. CommonPlan deduplicates it using `X-GitHub-Delivery`.

If the UI does not update, verify the delivery in three places in order: GitHub Recent Deliveries, the smee channel page/client output, and CommonPlan's Applications page. Signature failures usually mean the two secret values differ or a proxy changed the raw body.

## Security and lifecycle

- The endpoint is intentionally outside user JWT authentication. It authenticates the sender with the HMAC signature, numeric owner allowlist, optional hook ID, and unique delivery ID.
- The raw webhook payload and secret are not stored. CommonPlan stores a minimal PR snapshot, active/detached issue links, and delivery metadata.
- Only future deliveries are linked. M7 does not use a GitHub token to backfill existing PRs.
- Rotate the secret in both `.env` and GitHub webhook settings together, then restart the API and redeliver a test event.
