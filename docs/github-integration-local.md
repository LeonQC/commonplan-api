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

Get the numeric GitHub owner ID. This project accepts pull requests from the `wangd606` forks:

```bash
gh api users/wangd606 --jq '{login: .login, id: .id}'
```

The expected owner ID is `297650267`. Fetch it rather than relying only on the documented value so the setup remains verifiable.

Use the response's numeric `id`, not the login name, as the allowlist boundary. Repository webhooks from either an organization or a personal account expose this value as `repository.owner.id`.

## 2. Generate and configure the shared secret

Generate a new development secret locally:

```bash
openssl rand -hex 32
```

Add these values to the API repository's root `.env` file. Do not commit the file or paste the secret into an issue or PR.

```dotenv
GITHUB_WEBHOOK_SECRET=<generated value>
GITHUB_ALLOWED_OWNER_ID=297650267
GITHUB_ALLOWED_OWNER_LOGIN=wangd606
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

Do not commit a Smee channel URL. It is temporary public development infrastructure. Recover the currently configured URL from GitHub when needed:

```bash
gh api repos/wangd606/commonplan-api/hooks \
  --jq '.[] | select(.active and (.events | index("pull_request"))) | {id, url: .config.url}'
```

## 4. Add the GitHub webhook

Add the webhook to both fork repositories that should participate:

- `wangd606/commonplan-api`
- `wangd606/commonplan-web`

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

## Daily local runbook

The GitHub webhook remains configured on GitHub, but local forwarding only works while the API and Smee client are running.

1. Start the CommonPlan stack and apply pending migrations:

   ```bash
   docker compose up -d --build backend-migrate backend
   curl --fail http://localhost:8000/health
   ```

2. Recover the channel URL with the `gh api` command above, then start the forwarding daemon in a dedicated terminal:

   ```bash
   pnpm dlx smee-client \
     --url https://smee.io/YOUR_CHANNEL \
     --target http://localhost:8000/webhooks/github
   ```

3. Confirm that both fork repositories still have active pull-request webhooks:

   ```bash
   for repo in commonplan-api commonplan-web; do
     gh api "repos/wangd606/$repo/hooks" \
       --jq '.[] | {id, active, events, url: .config.url}'
   done
   ```

4. Confirm CommonPlan durably processed recent deliveries:

   ```bash
   docker exec project-zhitong-1-db-1 \
     psql -U zhitong -d zhitong \
     -c 'SELECT event_type, status, received_at, error_code FROM github_webhook_deliveries ORDER BY received_at DESC LIMIT 10;'
   ```

After a laptop restart, repeat steps 1 and 2. A stopped Smee client does not delete events from GitHub; use **Recent Deliveries → Redeliver** after the daemon is back online.

## Reference configuration

- Allowed GitHub owner: `wangd606` (`297650267`)
- Webhook repositories: `wangd606/commonplan-api`, `wangd606/commonplan-web`
- Event subscription: `pull_request` only
- Local target: `http://localhost:8000/webhooks/github`
- CommonPlan scope: one configured workspace through `GITHUB_WORKSPACE_ID`
- Link rule: an exact existing issue key in the PR title; no repository/project mapping

The secret and local workspace UUID belong in the untracked `.env` file. Do not put either value in this document, a PR description, or GitHub issue.

## Security and lifecycle

- The endpoint is intentionally outside user JWT authentication. It authenticates the sender with the HMAC signature, numeric owner allowlist, optional hook ID, and unique delivery ID.
- The raw webhook payload and secret are not stored. CommonPlan stores a minimal PR snapshot, active/detached issue links, and delivery metadata.
- Only future deliveries are linked. M7 does not use a GitHub token to backfill existing PRs.
- Rotate the secret in both `.env` and GitHub webhook settings together, then restart the API and redeliver a test event.
- When changing Smee channels, update the Payload URL on both repository webhooks before stopping the old client.
