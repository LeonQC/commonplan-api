from dataclasses import dataclass

from app.retrieval.types import ContextPassage, FusedHit, SearchHit


@dataclass
class _Candidate:
    hit: SearchHit
    rrf_score: float = 0.0
    vector_rank: int | None = None
    lexical_rank: int | None = None
    vector_score: float | None = None
    lexical_score: float | None = None


def reciprocal_rank_fusion(
    vector_hits: list[SearchHit],
    lexical_hits: list[SearchHit],
    *,
    rank_constant: int = 60,
) -> list[_Candidate]:
    """Fuse channel ranks without pretending their raw scores are comparable."""
    candidates: dict[str, _Candidate] = {}
    for method, hits in (("vector", vector_hits), ("lexical", lexical_hits)):
        for rank, hit in enumerate(hits, start=1):
            candidate = candidates.setdefault(hit.node_id, _Candidate(hit=hit))
            candidate.rrf_score += 1.0 / (rank_constant + rank)
            if method == "vector":
                candidate.vector_rank = rank
                candidate.vector_score = hit.score
            else:
                candidate.lexical_rank = rank
                candidate.lexical_score = hit.score
    return sorted(candidates.values(), key=lambda row: (-row.rrf_score, row.hit.node_id))


def _query_features(query: str) -> set[str]:
    lowered = query.casefold()
    words = {
        "".join(character for character in token if character.isalnum() or character in "-_./")
        for token in lowered.split()
    }
    words.discard("")
    cjk = [character for character in lowered if "\u3400" <= character <= "\u9fff"]
    words.update("".join(cjk[index:index + 2]) for index in range(max(0, len(cjk) - 1)))
    return words


def deterministic_rerank(
    query: str,
    candidates: list[_Candidate],
    contexts: dict[str, list[ContextPassage]],
) -> list[FusedHit]:
    """Apply an explainable local relevance pass after RRF and context expansion."""
    query_features = _query_features(query)
    query_phrase = " ".join(query.casefold().split())
    rows: list[FusedHit] = []
    for candidate in candidates:
        passages = contexts.get(candidate.hit.node_id, [])
        searchable = " ".join(
            [candidate.hit.content, *(passage.content for passage in passages)]
        ).casefold()
        matched = sum(feature in searchable for feature in query_features)
        coverage = matched / max(1, len(query_features))
        exact_phrase = bool(query_phrase and query_phrase in " ".join(searchable.split()))
        dual_channel = candidate.vector_rank is not None and candidate.lexical_rank is not None
        rerank_score = min(
            1.0,
            0.72 * coverage + 0.18 * float(exact_phrase) + 0.10 * float(dual_channel),
        )
        final_score = candidate.rrf_score * (1.0 + 0.25 * rerank_score)
        rows.append(FusedHit(
            hit=candidate.hit,
            rrf_score=candidate.rrf_score,
            rerank_score=rerank_score,
            final_score=final_score,
            vector_rank=candidate.vector_rank,
            lexical_rank=candidate.lexical_rank,
            vector_score=candidate.vector_score,
            lexical_score=candidate.lexical_score,
            context=tuple(passages),
        ))
    return sorted(rows, key=lambda row: (-row.final_score, row.hit.node_id))
