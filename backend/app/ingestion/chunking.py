from app.ingestion.types import ChunkDraft, ParsedDocument


CHUNKER_VERSION = "word-window-v1"


def count_tokens(text: str) -> int:
    """Dependency-free token estimate; the embedding adapter owns exact tokenization."""
    return len(text.split())


def chunk_document(
    document: ParsedDocument, *, chunk_tokens: int, overlap_tokens: int,
) -> list[ChunkDraft]:
    if chunk_tokens < 1 or overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("Chunk configuration is invalid")
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
                metadata={"word_start": start, "word_end": start + len(window)},
            ))
            if start + chunk_tokens >= len(words):
                break
    if not chunks:
        raise ValueError("Document contains no chunkable text")
    return chunks
