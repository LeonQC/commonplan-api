import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base
from app.models import User
from app.repositories.github_repository import SqlAlchemyGitHubRepository
from app.repositories.issue_repository import SqlAlchemyIssueRepository
from app.repositories.workspace_repository import SqlAlchemyWorkspaceRepository
from app.services.github_service import (
    GitHubIntegrationService,
    GitHubWebhookForbidden,
    GitHubWebhookUnauthorized,
)
from app.services.issue_service import IssueService
from app.services.workspace_service import WorkspaceService


SECRET = "local-test-secret"


def signed(raw_body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()


def payload(title: str, updated_at: str, *, owner_id: int = 101) -> dict:
    return {
        "action": "opened",
        "number": 12,
        "repository": {
            "id": 501,
            "full_name": "wangd606/commonplan-api",
            "owner": {"id": owner_id, "login": "wangd606"},
        },
        "pull_request": {
            "title": title,
            "html_url": "https://github.com/wangd606/commonplan-api/pull/12",
            "state": "open",
            "draft": False,
            "merged": False,
            "merged_at": None,
            "updated_at": updated_at,
        },
    }


@pytest.fixture
def context(monkeypatch):
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        owner = User(
            email="owner@example.com", name="Owner", auth_issuer="issuer",
            auth_subject="owner", is_deleted=False, created_at=now, updated_at=now,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        workspaces = WorkspaceService(SqlAlchemyWorkspaceRepository(db))
        workspace, _ = workspaces.create_workspace(
            owner, name="CommonPlan", slug="commonplan", description=None
        )
        team, _ = workspaces.create_team(
            owner, workspace.id, name="Core", issue_prefix="KEY", description=None
        )
        issues = IssueService(SqlAlchemyIssueRepository(db), workspaces)
        issue, _ = issues.create_issue(
            owner, workspace.id, team.id, title="Webhook target", label_ids=[]
        )
        repository = SqlAlchemyGitHubRepository(db)
        service = GitHubIntegrationService(repository, workspaces, issues)
        monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
        monkeypatch.setattr(settings, "github_allowed_owner_id", 101)
        monkeypatch.setattr(settings, "github_allowed_owner_login", "wangd606")
        monkeypatch.setattr(settings, "github_workspace_id", workspace.id)
        monkeypatch.setattr(settings, "github_hook_id", None)
        yield service, repository, owner, workspace, issue


def deliver(service, data: dict, delivery_id: str | None = None) -> dict:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return service.accept_webhook(
        raw_body=raw,
        payload=data,
        signature=signed(raw),
        delivery_id=delivery_id or str(uuid.uuid4()),
        event_type="pull_request",
        hook_id="99",
    )


def test_signed_pull_request_links_by_exact_title_key_and_deduplicates(context):
    service, repository, _owner, _workspace, issue = context
    data = payload(f"Ship {issue.key} integration", "2026-09-28T12:00:00Z")
    delivery_id = str(uuid.uuid4())

    first = deliver(service, data, delivery_id)
    duplicate = deliver(service, data, delivery_id)

    assert first["linked_issue_keys"] == [issue.key]
    assert duplicate["duplicate"] is True
    assert len(repository.linked_pull_requests(issue.id)) == 1
    assert repository.delivery_counts() == {"processed": 1}


def test_title_edit_detaches_link_when_exact_key_disappears(context):
    service, repository, _owner, _workspace, issue = context
    deliver(service, payload(f"Ship {issue.key}", "2026-09-28T12:00:00Z"))
    changed = payload(f"Ship {issue.key}0", "2026-09-28T12:01:00Z")
    changed["action"] = "edited"

    deliver(service, changed)

    assert repository.linked_pull_requests(issue.id) == []


def test_invalid_signature_and_unknown_owner_are_rejected(context):
    service, repository, _owner, _workspace, issue = context
    data = payload(f"Ship {issue.key}", "2026-09-28T12:00:00Z")
    raw = json.dumps(data).encode()

    with pytest.raises(GitHubWebhookUnauthorized):
        service.accept_webhook(
            raw_body=raw, payload=data, signature="sha256=bad",
            delivery_id=str(uuid.uuid4()), event_type="pull_request", hook_id=None,
        )
    with pytest.raises(GitHubWebhookForbidden):
        unknown = payload(f"Ship {issue.key}", "2026-09-28T12:00:00Z", owner_id=999)
        unknown_raw = json.dumps(unknown).encode()
        service.accept_webhook(
            raw_body=unknown_raw, payload=unknown, signature=signed(unknown_raw),
            delivery_id=str(uuid.uuid4()), event_type="pull_request", hook_id=None,
        )

    assert repository.delivery_counts() == {}
