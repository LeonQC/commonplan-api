from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CommentMention, User
from app.repositories.collaboration_repository import SqlAlchemyCollaborationRepository
from app.repositories.issue_repository import SqlAlchemyIssueRepository
from app.repositories.workspace_repository import SqlAlchemyWorkspaceRepository
from app.services.collaboration_service import CollaborationService
from app.services.issue_service import IssueService
from app.services.resource_policy import ResourceForbidden
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        owner = User(email="owner@example.com", name="Owner", auth_issuer="issuer", auth_subject="owner", is_deleted=False, created_at=now, updated_at=now)
        teammate = User(email="team@example.com", name="Teammate", auth_issuer="issuer", auth_subject="team", is_deleted=False, created_at=now, updated_at=now)
        observer = User(email="observer@example.com", name="Observer", auth_issuer="issuer", auth_subject="observer", is_deleted=False, created_at=now, updated_at=now)
        db.add_all([owner, teammate, observer])
        db.commit()
        for user in (owner, teammate, observer): db.refresh(user)
        workspace_repository = SqlAlchemyWorkspaceRepository(db)
        workspaces = WorkspaceService(workspace_repository)
        workspace, _ = workspaces.create_workspace(owner, name="CommonPlan", slug="commonplan", description=None)
        for user in (teammate, observer): workspaces.put_workspace_member(owner, workspace.id, user.id, "member")
        team, _ = workspaces.create_team(owner, workspace.id, name="Core", issue_prefix="KEY", description=None)
        for user in (teammate, observer): workspaces.put_team_member(owner, workspace.id, team.id, user.id, "member")
        issue_repository = SqlAlchemyIssueRepository(db)
        issues = IssueService(issue_repository, workspaces)
        collaboration = CollaborationService(SqlAlchemyCollaborationRepository(db), workspaces, issues)
        parent, _ = issues.create_issue(owner, workspace.id, team.id, title="Parent", label_ids=[])
        yield db, collaboration, workspaces, owner, teammate, observer, workspace, team, parent


def test_comment_mentions_watchers_and_sub_issues(context):
    db, collaboration, _workspaces, owner, teammate, _observer, workspace, _team, parent = context

    comment = collaboration.create_comment(teammate, workspace.id, parent.key, "Please review @Owner", [owner.id])
    state = collaboration.collaboration(teammate, workspace.id, parent.key)
    child, _labels = collaboration.create_sub_issue(teammate, workspace.id, parent.key, {"title": "Child", "label_ids": []})

    assert {user.id for _watcher, user in state["watchers"]} == {owner.id, teammate.id}
    assert db.get(CommentMention, (comment["id"], owner.id)) is not None
    assert child.parent_issue_id == parent.id
    assert collaboration.collaboration(owner, workspace.id, parent.key)["children"][0].id == child.id


def test_comment_policy_and_removed_member_access(context):
    _db, collaboration, workspaces, owner, teammate, observer, workspace, team, parent = context
    comment = collaboration.create_comment(teammate, workspace.id, parent.key, "Initial")

    with pytest.raises(ResourceForbidden):
        collaboration.update_comment(observer, workspace.id, parent.key, comment["id"], "Not allowed")

    updated = collaboration.update_comment(owner, workspace.id, parent.key, comment["id"], "Owner moderation")
    assert updated["body"] == "Owner moderation"

    workspaces.delete_team_member(owner, workspace.id, team.id, teammate.id)
    with pytest.raises(ResourceForbidden):
        collaboration.collaboration(teammate, workspace.id, parent.key)
