from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.main import app
from app.models import User
from app.repositories.retrieval_repository import SqlAlchemyRetrievalRepository
from app.retrieval.types import RetrievalScope, SearchHit
from app.schemas import RetrievalSearchResponse
from app.services.retrieval_service import RetrievalForbidden, RetrievalService


class FakeTeam:
    def __init__(self, team_id):
        self.id = team_id


class FakeWorkspaces:
    def __init__(self, team_ids):
        self.team_ids = team_ids

    def get_workspace(self, _user, _workspace_id):
        return object(), object()

    def list_teams(self, _user, _workspace_id):
        return [(FakeTeam(team_id), None) for team_id in self.team_ids]


class FakeEmbeddingProvider:
    provider = "model_gateway"
    model = "commonplan-embedding-v1:Qwen/Qwen3-Embedding-0.6B@revision"
    dimensions = 3

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.0, 0.0] for _text in texts]


class FakeRepository:
    def __init__(self):
        self.vector_calls = []
        self.lexical_calls = []

    def vector_search(self, vector, profile_key, scope, limit):
        self.vector_calls.append((vector, profile_key, scope, limit))
        return [hit("vector", scope)]

    def lexical_search(self, query, scope, limit):
        self.lexical_calls.append((query, scope, limit))
        return [hit("lexical", scope)]


def hit(method, scope):
    return SearchHit(
        node_id=f"{method}-node",
        source_id="issue-1",
        source_type="issue",
        content="TA-1 login failure",
        method=method,
        score=0.8,
        workspace_id=scope.workspace_id,
        team_id=scope.team_ids[0],
        issue_id="issue-1",
    )


def user():
    now = datetime.now(timezone.utc)
    return User(
        id=1,
        email="owner@example.com",
        name="Owner",
        auth_issuer="issuer",
        auth_subject="subject",
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


def test_both_search_channels_share_server_derived_scope_and_profile():
    repository = FakeRepository()
    embedding = FakeEmbeddingProvider()
    service = RetrievalService(
        repository,
        FakeWorkspaces(["team-b", "team-a"]),
        embedding,
    )

    result = service.search(
        user(),
        "workspace-1",
        query="Why did TA-1 fail?",
        mode="both",
        team_ids=["team-a"],
        project_id=None,
        issue_id="issue-1",
        limit=5,
    )

    assert result["scope"] == {
        "workspace_id": "workspace-1",
        "team_ids": ["team-a"],
        "project_id": None,
        "issue_id": "issue-1",
    }
    assert [row.method for row in result["vector_results"]] == ["vector"]
    assert [row.method for row in result["lexical_results"]] == ["lexical"]
    assert embedding.calls == [["Why did TA-1 fail?"]]
    assert repository.vector_calls[0][1].endswith(":3")
    assert repository.vector_calls[0][2] == repository.lexical_calls[0][1]
    serialized = RetrievalSearchResponse.model_validate(result).model_dump()
    assert serialized["vector_results"][0]["citation_target"] == "issue:issue-1"


def test_lexical_only_search_does_not_call_embedding_model():
    repository = FakeRepository()
    embedding = FakeEmbeddingProvider()
    service = RetrievalService(repository, FakeWorkspaces(["team-a"]), embedding)

    result = service.search(
        user(), "workspace-1", query="TA-1", mode="lexical",
        team_ids=None, project_id=None, issue_id=None, limit=10,
    )

    assert embedding.calls == []
    assert repository.vector_calls == []
    assert len(result["lexical_results"]) == 1
    assert result["embedding_profile_key"] is None


def test_requested_team_must_be_authorized_before_repository_call():
    repository = FakeRepository()
    service = RetrievalService(
        repository,
        FakeWorkspaces(["team-a"]),
        FakeEmbeddingProvider(),
    )

    with pytest.raises(RetrievalForbidden):
        service.search(
            user(), "workspace-1", query="private", mode="both",
            team_ids=["team-b"], project_id=None, issue_id=None, limit=10,
        )

    assert repository.vector_calls == []
    assert repository.lexical_calls == []


class EmptyRows:
    def all(self):
        return []


class CapturingSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return EmptyRows()


def compiled(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


def test_repository_places_acl_and_lifecycle_filters_inside_both_queries():
    session = CapturingSession()
    repository = SqlAlchemyRetrievalRepository(session)
    scope = RetrievalScope(
        workspace_id="workspace-1",
        team_ids=("team-a", "team-b"),
        project_id="project-1",
    )

    repository.vector_search([1.0, 0.0, 0.0], "profile", scope, 5)
    repository.lexical_search("TA-1", scope, 5)

    iterative_sql = compiled(session.statements[0])
    vector_sql = compiled(session.statements[1])
    lexical_sql = compiled(session.statements[2])
    assert "hnsw.iterative_scan = 'strict_order'" in iterative_sql
    for sql in (vector_sql, lexical_sql):
        assert "knowledge_nodes.workspace_id" in sql
        assert "knowledge_nodes.team_id IN" in sql
        assert "knowledge_sources.workspace_id" in sql
        assert "knowledge_sources.team_id IN" in sql
        assert "knowledge_nodes.project_id" in sql
        assert "knowledge_nodes.indexable IS true" in sql
        assert "knowledge_sources.status" in sql
        assert "knowledge_sources.deleted_at IS NULL" in sql
    assert "embedding_profiles.profile_key" in vector_sql
    assert "knowledge_embeddings.embedding_profile_key" in vector_sql
    assert "knowledge_sources.active_embedding_profile_id" in vector_sql
    assert "vector_dims" in vector_sql
    assert "to_tsvector" in lexical_sql
    assert "similarity" in lexical_sql


def test_search_hit_exposes_stable_citation_target():
    scope = RetrievalScope("workspace-1", ("team-a",))
    assert hit("vector", scope).citation_target == "issue:issue-1"


def test_retrieval_route_is_fail_closed_without_access_token():
    response = TestClient(app).post(
        "/api/v1/workspaces/workspace-1/retrieval/search",
        json={"query": "TA-1", "mode": "lexical"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
