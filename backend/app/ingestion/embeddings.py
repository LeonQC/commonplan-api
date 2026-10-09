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


class TEIEmbeddingProvider:
    """Client for the private Text Embeddings Inference service."""

    provider = "tei"

    def __init__(
        self,
        base_url: str,
        model: str,
        revision: str,
        dimensions: int,
        *,
        batch_size: int = 3,
        timeout_seconds: float = 120,
    ) -> None:
        if not base_url:
            raise ValueError("INGESTION_EMBEDDING_BASE_URL is required for TEI embeddings")
        if batch_size < 1:
            raise ValueError("INGESTION_EMBEDDING_BATCH_SIZE must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = f"{model}@{revision}"
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            response = httpx.post(
                f"{self.base_url}/embed",
                json={
                    "inputs": texts[start:start + self.batch_size],
                    "truncate": True,
                    "normalize": True,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("TEI returned a non-list embedding response")
            vectors.extend(self._validated(vector) for vector in payload)
        if len(vectors) != len(texts):
            raise ValueError("TEI embedding count does not match input count")
        return vectors

    def _validated(self, vector) -> list[float]:
        if not isinstance(vector, list) or len(vector) != self.dimensions:
            actual = len(vector) if isinstance(vector, list) else "invalid"
            raise ValueError(
                f"TEI returned {actual} dimensions; expected {self.dimensions}"
            )
        converted = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in converted):
            raise ValueError("TEI returned a non-finite embedding")
        norm = math.sqrt(sum(value * value for value in converted))
        if norm == 0:
            raise ValueError("TEI returned a zero embedding")
        # Normalize defensively so the persisted cosine profile is stable even
        # if a serving option changes during an operational rollout.
        return [value / norm for value in converted]


def create_embedding_provider() -> EmbeddingProvider:
    if settings.ingestion_embedding_provider == "tei":
        return TEIEmbeddingProvider(
            settings.ingestion_embedding_base_url,
            settings.ingestion_embedding_model,
            settings.ingestion_embedding_model_revision,
            settings.ingestion_embedding_dimensions,
            batch_size=settings.ingestion_embedding_batch_size,
            timeout_seconds=settings.ingestion_embedding_timeout_seconds,
        )
    if settings.ingestion_embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            settings.ingestion_embedding_model,
            settings.openai_api_key,
            settings.ingestion_embedding_dimensions,
        )
    if settings.ingestion_embedding_provider == "local_hash":
        return LocalHashEmbeddingProvider(settings.ingestion_embedding_dimensions)
    raise ValueError(f"Unknown embedding provider: {settings.ingestion_embedding_provider}")
