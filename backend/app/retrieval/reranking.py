import re

from app.retrieval.types import RetrievalCandidate


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.lower()))


def rerank(
    query: str, candidates: list[RetrievalCandidate], *, limit: int, min_score: float,
) -> list[tuple[RetrievalCandidate, float, float]]:
    query_terms = _terms(query)
    ranked = []
    for candidate in candidates:
        content_terms = _terms(candidate.chunk_content)
        lexical_score = (
            len(query_terms & content_terms) / len(query_terms) if query_terms else 0.0
        )
        normalized_vector = max(0.0, min(1.0, (candidate.vector_score + 1.0) / 2.0))
        score = 0.75 * normalized_vector + 0.25 * lexical_score
        if score >= min_score:
            ranked.append((candidate, score, lexical_score))
    ranked.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return ranked[:limit]
