def recall_at_k(
    ranked_ids: list[str], relevant_ids: set[str], k: int,
) -> float:
    if not relevant_ids:
        return 1.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, candidate_id in enumerate(ranked_ids, start=1):
        if candidate_id in relevant_ids:
            return 1.0 / rank
    return 0.0
