#!/usr/bin/env python3
"""Verify the isolated local LiteLLM MCP gateway boundary."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request_json(url: str, *, api_key: str | None = None):
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def initialize_mcp(url: str, *, api_key: str):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "commonplan-smoke", "version": "1.0"},
        },
    }
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-litellm-api-key": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode()
        data_line = next(
            (line.removeprefix("data: ") for line in body.splitlines() if line.startswith("data: ")),
            None,
        )
        return response.status, json.loads(data_line) if data_line else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-url", default="http://127.0.0.1:4001")
    parser.add_argument("--gateway-key", default="sk-local-commonplan-mcp-change-me")
    parser.add_argument(
        "--allow-configured-servers",
        action="store_true",
        help="Accept a non-empty registry after reviewed upstream servers are added.",
    )
    args = parser.parse_args()
    base_url = args.gateway_url.rstrip("/")

    status, health = request_json(f"{base_url}/health/liveliness")
    if status != 200:
        raise SystemExit(f"MCP gateway health failed with HTTP {status}")

    try:
        request_json(f"{base_url}/v1/mcp/server")
    except HTTPError as error:
        if error.code != 401:
            raise SystemExit(f"unauthenticated registry returned HTTP {error.code}") from error
    else:
        raise SystemExit("unauthenticated MCP registry request unexpectedly succeeded")

    status, servers = request_json(
        f"{base_url}/v1/mcp/server",
        api_key=args.gateway_key,
    )
    if status != 200 or not isinstance(servers, list):
        raise SystemExit("authenticated MCP registry did not return a server list")
    if servers and not args.allow_configured_servers:
        raise SystemExit(
            "MCP registry is not empty; review the configured servers or pass "
            "--allow-configured-servers"
        )

    initialize_status, initialize = initialize_mcp(
        f"{base_url}/mcp/",
        api_key=args.gateway_key,
    )
    server_info = (initialize or {}).get("result", {}).get("serverInfo", {})
    if initialize_status != 200 or server_info.get("name") != "litellm-mcp-server":
        raise SystemExit("MCP protocol initialization failed")

    print(
        f"health={health!r} unauthenticated=401 "
        f"authenticated=200 mcp_initialize=200 registered_servers={len(servers)}"
    )


if __name__ == "__main__":
    main()
