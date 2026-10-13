from functools import lru_cache

from app.config import settings
from app.ingestion.types import ChunkDraft, ParsedDocument


CHUNKER_VERSION = "docling-hybrid-v1"


def count_tokens(text: str) -> int:
    """Portable fallback count for persisted parent pages."""
    return len(text.split())


def chunk_document(
    document: ParsedDocument, *, chunk_tokens: int, overlap_tokens: int,
) -> list[ChunkDraft]:
    if chunk_tokens < 1 or overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("Chunk configuration is invalid")
    if document.native_document is not None:
        return _chunk_docling(document, chunk_tokens)
    return _chunk_words(document, chunk_tokens, overlap_tokens)


def _chunk_words(
    document: ParsedDocument, chunk_tokens: int, overlap_tokens: int,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    step = chunk_tokens - overlap_tokens
    for page in document.pages:
        words = page.plain_text.split()
        for start in range(0, len(words), step):
            window = words[start:start + chunk_tokens]
            if not window:
                break
            chunks.append(ChunkDraft(
                chunk_index=len(chunks),
                page_number=page.page_number,
                content=" ".join(window),
                token_count=len(window),
                heading_path=page.heading_path,
                metadata={"strategy": "word_window", "word_start": start, "word_end": start + len(window)},
            ))
            if start + chunk_tokens >= len(words):
                break
    if not chunks:
        raise ValueError("Document contains no chunkable text")
    return chunks


@lru_cache(maxsize=4)
def _docling_chunker(model: str, revision: str, max_tokens: int):
    try:
        from docling.chunking import HybridChunker
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Docling chunking dependencies are unavailable") from exc
    tokenizer = AutoTokenizer.from_pretrained(model, revision=revision)
    wrapped = HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=max_tokens)
    return HybridChunker(tokenizer=wrapped, merge_peers=True), wrapped


def _chunk_docling(document: ParsedDocument, max_tokens: int) -> list[ChunkDraft]:
    chunker, tokenizer = _docling_chunker(
        settings.ingestion_embedding_model,
        settings.ingestion_embedding_model_revision,
        max_tokens,
    )
    valid_pages = {page.page_number for page in document.pages}
    fallback_page = min(valid_pages)
    drafts: list[ChunkDraft] = []
    for chunk in chunker.chunk(dl_doc=document.native_document):
        content = chunker.contextualize(chunk=chunk).strip()
        if not content:
            continue
        page_numbers = {
            provenance.page_no
            for item in getattr(chunk.meta, "doc_items", [])
            for provenance in getattr(item, "prov", [])
            if getattr(provenance, "page_no", None) in valid_pages
        }
        headings = [str(value).strip() for value in getattr(chunk.meta, "headings", []) if value]
        drafts.append(ChunkDraft(
            chunk_index=len(drafts),
            page_number=min(page_numbers) if page_numbers else fallback_page,
            content=content,
            token_count=tokenizer.count_tokens(content),
            heading_path=" > ".join(headings[-3:]) if headings else None,
            metadata={
                "strategy": "docling_hybrid",
                "page_numbers": sorted(page_numbers),
                "docling": chunk.meta.export_json_dict(),
            },
        ))
    if not drafts:
        raise ValueError("Document contains no chunkable text")
    return drafts
