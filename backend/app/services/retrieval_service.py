from typing import Annotated, Literal

import httpx
from fastapi import Depends

from app.ingestion.embedding_profiles import embedding_profile_key
from app.ingestion.embeddings import EmbeddingProvider, create_embedding_provider
from app.models import User
from app.repositories.retrieval_repository import RetrievalRepository, RetrievalRepositoryDep
from app.retrieval.types import RetrievalScope, SearchHit
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class RetrievalNotFound(Exception):
    pass


class RetrievalForbidden(Exception):
    pass


class RetrievalUnavailable(Exception):
    pass


class RetrievalService:
    """Derive caller scope before delegating all database work to the repository."""

    def __init__(
        self,
        repository: RetrievalRepository,
        workspaces: WorkspaceService,
        embedding_provider: EmbeddingProvider,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.embedding_provider = embedding_provider

    def search(
        self,
        user: User,
        workspace_id: str,
        *,
        query: str,
        mode: Literal["vector", "lexical", "both"],
        team_ids: list[str] | None,
        project_id: str | None,
        issue_id: str | None,
        limit: int,
    ) -> dict:
        scope = self._scope(user, workspace_id, team_ids, project_id, issue_id)
        if not scope.team_ids:
            return self._result(scope, None, [], [])

        lexical_hits: list[SearchHit] = []
        vector_hits: list[SearchHit] = []
        if mode in {"lexical", "both"}:
            lexical_hits = self.repository.lexical_search(query, scope, limit)

        profile_key = None
        if mode in {"vector", "both"}:
            try:
                vectors = self.embedding_provider.embed([query])
            except (httpx.HTTPError, ValueError) as exc:
                raise RetrievalUnavailable("Query embedding is unavailable") from exc
            if len(vectors) != 1:
                raise RetrievalUnavailable("Query embedding returned an invalid result")
            profile_key = embedding_profile_key(
                self.embedding_provider.provider,
                self.embedding_provider.model,
                self.embedding_provider.dimensions,
            )
            vector_hits = self.repository.vector_search(
                vectors[0], profile_key, scope, limit
            )
        return self._result(scope, profile_key, vector_hits, lexical_hits)

    def _scope(
        self,
        user: User,
        workspace_id: str,
        requested_team_ids: list[str] | None,
        project_id: str | None,
        issue_id: str | None,
    ) -> RetrievalScope:
        try:
            self.workspaces.get_workspace(user, workspace_id)
            authorized_rows = self.workspaces.list_teams(user, workspace_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"):
                raise RetrievalNotFound from exc
            raise RetrievalForbidden from exc

        authorized = {team.id for team, _membership in authorized_rows}
        requested = set(requested_team_ids or [])
        if requested and not requested.issubset(authorized):
            raise RetrievalForbidden
        selected = sorted(requested or authorized)
        return RetrievalScope(
            workspace_id=workspace_id,
            team_ids=tuple(selected),
            project_id=project_id,
            issue_id=issue_id,
        )

    @staticmethod
    def _result(scope, profile_key, vector_hits, lexical_hits) -> dict:
        return {
            "scope": {
                "workspace_id": scope.workspace_id,
                "team_ids": list(scope.team_ids),
                "project_id": scope.project_id,
                "issue_id": scope.issue_id,
            },
            "embedding_profile_key": profile_key,
            "vector_results": vector_hits,
            "lexical_results": lexical_hits,
        }


def get_query_embedding_provider() -> EmbeddingProvider:
    return create_embedding_provider()


QueryEmbeddingProviderDep = Annotated[
    EmbeddingProvider,
    Depends(get_query_embedding_provider),
]


def get_retrieval_service(
    repository: RetrievalRepositoryDep,
    workspaces: WorkspaceServiceDep,
    embedding_provider: QueryEmbeddingProviderDep,
) -> RetrievalService:
    return RetrievalService(repository, workspaces, embedding_provider)


RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]
