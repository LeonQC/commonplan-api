import math

import httpx
import pytest

from app.ingestion.embeddings import TEIEmbeddingProvider, create_embedding_provider
from app.ingestion.parsers import ParserRegistry
from app.ingestion.types import ParsedDocument, ParsedPage


class FakeDoclingParser:
    name = "docling"
    version = "test"

    def __init__(self):
        self.calls = []

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        self.calls.append((content, filename))
        return ParsedDocument(
            self.name,
            self.version,
            [ParsedPage(1, "# Parsed", "Parsed", "Parsed")],
            native_document=object(),
        )


def test_registry_routes_office_files_to_docling_and_preserves_filename():
    docling = FakeDoclingParser()
    document = ParserRegistry(docling).parse(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"docx bytes",
        "product-plan.docx",
    )

    assert document.parser_name == "docling"
    assert docling.calls == [(b"docx bytes", "product-plan.docx")]


def test_tei_provider_batches_validates_and_normalizes(monkeypatch):
    requests = []

    def fake_post(url, *, json, timeout):
        requests.append((url, json, timeout))
        vectors = [[3.0, 4.0, 0.0] for _ in json["inputs"]]
        return httpx.Response(200, json=vectors, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = TEIEmbeddingProvider(
        "http://embedding-service/",
        "Qwen/Qwen3-Embedding-0.6B",
        "revision",
        3,
        batch_size=2,
        timeout_seconds=10,
    )

    vectors = provider.embed(["one", "two", "three"])

    assert len(requests) == 2
    assert requests[0][0] == "http://embedding-service/embed"
    assert requests[0][1] == {
        "inputs": ["one", "two"], "truncate": True, "normalize": True,
    }
    assert provider.model == "Qwen/Qwen3-Embedding-0.6B@revision"
    assert all(math.isclose(sum(value * value for value in vector), 1.0) for vector in vectors)


def test_tei_provider_rejects_wrong_dimensions(monkeypatch):
    def fake_post(url, *, json, timeout):
        return httpx.Response(200, json=[[1.0, 2.0]], request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = TEIEmbeddingProvider("http://embedding-service", "model", "revision", 3)

    with pytest.raises(ValueError, match="expected 3"):
        provider.embed(["text"])


def test_embedding_factory_never_silently_falls_back(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ingestion_embedding_provider", "unknown")
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        create_embedding_provider()
