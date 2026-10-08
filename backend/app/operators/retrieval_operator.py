from typing import Annotated

from fastapi import Depends

from app.config import settings
from app.ingestion.embeddings import EmbeddingProvider, create_embedding_provider
from app.repositories.retrieval_repository import RetrievalRepository, RetrievalRepositoryDep
from app.retrieval.reranking import rerank


class RetrievalOperator:
    """Coordinates embedding and repository search without exposing a DB session."""

    def __init__(self, repository: RetrievalRepository, embeddings: EmbeddingProvider) -> None:
        self.repository = repository
        self.embeddings = embeddings

    def search(
        self,
        *,
        workspace_id: str,
        allowed_team_ids: list[str],
        query: str,
        limit: int,
        team_id: str | None,
        issue_key: str | None,
        project_id: str | None,
    ) -> dict:
        query_vector = self.embeddings.embed([query])[0]
        candidate_limit = min(100, max(limit, limit * settings.retrieval_candidate_multiplier))
        candidates = self.repository.nearest(
            workspace_id=workspace_id,
            allowed_team_ids=allowed_team_ids,
            query_vector=query_vector,
            embedding_provider=self.embeddings.provider,
            embedding_model=self.embeddings.model,
            candidate_limit=candidate_limit,
            team_id=team_id,
            issue_key=issue_key,
            project_id=project_id,
        )
        ranked = rerank(
            query, candidates, limit=limit, min_score=settings.retrieval_min_score
        )
        return {
            "query": query,
            "embedding_provider": self.embeddings.provider,
            "embedding_model": self.embeddings.model,
            "candidate_count": len(candidates),
            "results": [self._result(candidate, score, lexical) for candidate, score, lexical in ranked],
        }

    @staticmethod
    def _result(candidate, score: float, lexical_score: float) -> dict:
        resource_type = "issue" if candidate.issue_id else "project"
        resource_key = candidate.issue_key or candidate.project_id
        return {
            "chunk_id": candidate.chunk_id,
            "score": round(score, 6),
            "vector_score": round(candidate.vector_score, 6),
            "lexical_score": round(lexical_score, 6),
            "excerpt": candidate.chunk_content,
            "context": candidate.parent_content[:settings.retrieval_parent_max_chars],
            "citation": {
                "file_asset_id": candidate.file_asset_id,
                "filename": candidate.filename,
                "page_number": candidate.page_number,
                "heading_path": candidate.heading_path,
                "team_id": candidate.team_id,
                "resource_type": resource_type,
                "resource_id": candidate.issue_id or candidate.project_id,
                "resource_key": resource_key,
            },
        }


def get_retrieval_operator(repository: RetrievalRepositoryDep) -> RetrievalOperator:
    return RetrievalOperator(repository, create_embedding_provider())


RetrievalOperatorDep = Annotated[RetrievalOperator, Depends(get_retrieval_operator)]
