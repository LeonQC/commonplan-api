from types import SimpleNamespace

import pytest

from app.operators.retrieval_operator import RetrievalOperator
from app.retrieval.types import RetrievalCandidate
from app.services.retrieval_service import (
    RetrievalForbidden, RetrievalService, RetrievalValidationError,
)


class FakeEmbeddings:
    provider = "local_hash"
    model = "local-hash-v1"
    dimensions = 3

    def embed(self, texts):
        assert texts
        return [[1.0, 0.0, 0.0] for _text in texts]


class FakeRetrievalRepository:
    def __init__(self, candidates):
        self.candidates = candidates
        self.call = None

    def nearest(self, **kwargs):
        self.call = kwargs
        return self.candidates


class FakeWorkspaces:
    def __init__(self, team_ids):
        self.team_ids = team_ids

    def list_teams(self, _user, _workspace_id):
        return [(SimpleNamespace(id=team_id), None) for team_id in self.team_ids]


def candidate(chunk_id, content, vector_score, *, team_id="team-1"):
    return RetrievalCandidate(
        chunk_id=chunk_id,
        file_asset_id="file-1",
        filename="rag.md",
        team_id=team_id,
        issue_id="issue-1",
        issue_key="KEY-11",
        project_id=None,
        project_name=None,
        page_number=2,
        heading_path="Retrieval",
        chunk_content=content,
        parent_content=f"Parent context for {content}",
        vector_score=vector_score,
    )


def test_retrieval_applies_acl_before_search_and_reranks_candidates():
    repository = FakeRetrievalRepository([
        candidate("vector-only", "different words", 0.70),
        candidate("lexical-match", "refresh token rotation", 0.50),
    ])
    operator = RetrievalOperator(repository, FakeEmbeddings())
    service = RetrievalService(operator, FakeWorkspaces(["team-1", "team-2"]))

    result = service.search(SimpleNamespace(id=1), "workspace-1", {
        "query": "refresh token", "limit": 2, "team_id": "team-1",
        "issue_key": None, "project_id": None,
    })

    assert repository.call["allowed_team_ids"] == ["team-1", "team-2"]
    assert repository.call["team_id"] == "team-1"
    assert result["results"][0]["chunk_id"] == "lexical-match"
    citation = result["results"][0]["citation"]
    assert citation["resource_type"] == "issue"
    assert citation["resource_key"] == "KEY-11"
    assert citation["page_number"] == 2


def test_retrieval_rejects_team_outside_callers_acl():
    service = RetrievalService(
        RetrievalOperator(FakeRetrievalRepository([]), FakeEmbeddings()),
        FakeWorkspaces(["team-1"]),
    )
    with pytest.raises(RetrievalForbidden):
        service.search(SimpleNamespace(id=1), "workspace-1", {
            "query": "secret", "limit": 5, "team_id": "team-2",
            "issue_key": None, "project_id": None,
        })


def test_retrieval_rejects_ambiguous_resource_filter_and_blank_query():
    service = RetrievalService(
        RetrievalOperator(FakeRetrievalRepository([]), FakeEmbeddings()),
        FakeWorkspaces(["team-1"]),
    )
    with pytest.raises(RetrievalValidationError):
        service.search(SimpleNamespace(id=1), "workspace-1", {
            "query": "query", "limit": 5, "team_id": None,
            "issue_key": "KEY-11", "project_id": "project-1",
        })
    with pytest.raises(RetrievalValidationError):
        service.search(SimpleNamespace(id=1), "workspace-1", {
            "query": "   ", "limit": 5, "team_id": None,
            "issue_key": None, "project_id": None,
        })
