from hashlib import blake2b
import math
from typing import Protocol

import httpx

from app.config import settings


class EmbeddingProvider(Protocol):
    provider: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbeddingProvider:
    """Deterministic local development adapter, not a semantic production model."""

    provider = "local_hash"
    model = "local-hash-v1"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = blake2b(token.encode(), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            vector[index] += 1.0 if digest[8] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAIEmbeddingProvider:
    provider = "openai"

    def __init__(self, model: str, api_key: str, dimensions: int) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dimensions},
            timeout=60,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]


def create_embedding_provider() -> EmbeddingProvider:
    if settings.ingestion_embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            settings.ingestion_embedding_model,
            settings.openai_api_key,
            settings.ingestion_embedding_dimensions,
        )
    return LocalHashEmbeddingProvider(settings.ingestion_embedding_dimensions)
