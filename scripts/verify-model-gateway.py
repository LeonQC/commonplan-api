#!/usr/bin/env python3
"""Compare direct TEI and LiteLLM embeddings for the pinned CommonPlan profile."""

from __future__ import annotations

import argparse
import json
import math
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict, *, api_key: str | None = None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tei-url", default="http://localhost:8080")
    parser.add_argument("--gateway-url", default="http://localhost:4000/v1")
    parser.add_argument("--gateway-key", default="sk-local-commonplan-change-me")
    parser.add_argument("--alias", default="commonplan-embedding-v1")
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--minimum-cosine", type=float, default=0.99999)
    args = parser.parse_args()

    text = "CommonPlan links issue attachments to permission-scoped project knowledge."
    direct_payload = post_json(
        f"{args.tei_url.rstrip('/')}/embed",
        {"inputs": [text], "truncate": True, "normalize": True},
    )
    gateway_payload = post_json(
        f"{args.gateway_url.rstrip('/')}/embeddings",
        {"model": args.alias, "input": [text], "encoding_format": "float"},
        api_key=args.gateway_key,
    )
    direct = [float(value) for value in direct_payload[0]]
    gateway = [float(value) for value in gateway_payload["data"][0]["embedding"]]
    if len(direct) != args.dimensions or len(gateway) != args.dimensions:
        raise SystemExit(
            f"dimension mismatch: direct={len(direct)} gateway={len(gateway)} "
            f"expected={args.dimensions}"
        )
    direct_norm = norm(direct)
    gateway_norm = norm(gateway)
    cosine = sum(a * b for a, b in zip(direct, gateway, strict=True)) / (
        direct_norm * gateway_norm
    )
    print(
        f"dimensions={args.dimensions} direct_norm={direct_norm:.6f} "
        f"gateway_norm={gateway_norm:.6f} cosine={cosine:.8f}"
    )
    if not math.isfinite(cosine) or cosine < args.minimum_cosine:
        raise SystemExit(
            f"gateway embedding is not conformant: {cosine:.8f} < {args.minimum_cosine}"
        )


if __name__ == "__main__":
    main()
