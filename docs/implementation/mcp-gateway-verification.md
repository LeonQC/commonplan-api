# Verify the optional MCP tool gateway

CommonPlan uses the same LiteLLM distribution for model and MCP capabilities, but runs them as
separate deployables. The model gateway on port `4000` owns model aliases and provider credentials.
The optional tool gateway on port `4001` owns the MCP registry and tool traffic.

## Start the empty local registry

```bash
docker compose --profile mcp up -d tool-gateway
python scripts/verify-mcp-gateway.py
```

Expected output:

```text
health="I'm alive!" unauthenticated=401 authenticated=200 mcp_initialize=200 registered_servers=0
```

The empty registry is the expected initial state. It verifies that the MCP boundary is independently
deployable and authenticated without pretending that an upstream integration is ready.

## Registering an upstream later

Before adding an entry under `mcp_servers` in `deploy/litellm/mcp-config.yaml`, document and test:

- the server owner and supported transport (`http`, `sse`, or `stdio`);
- service credentials or per-user OAuth custody and refresh behavior;
- how CommonPlan workspace, user, and resource scope reaches the server;
- the exact allowed tools, resources and prompts;
- which operations need explicit user approval;
- tool-call audit fields, redaction and retention;
- outbound network destinations and timeouts;
- revocation, incident response and failure behavior.

After a reviewed server is added, use:

```bash
python scripts/verify-mcp-gateway.py --allow-configured-servers
```

That flag changes only the smoke-test expectation; it does not approve or authorize a server.

## Production topology

Deploy the model and MCP gateways as separate workloads with different credentials, network policy,
egress, scaling, audit configuration and control-plane database credentials. They may use the same
LiteLLM version, but should use separate gateway databases—or database roles/schemas with equivalent
enforced isolation—so an MCP exposure cannot disclose model-provider configuration or keys. The MCP
endpoint remains private unless an explicitly reviewed external client requires it.

