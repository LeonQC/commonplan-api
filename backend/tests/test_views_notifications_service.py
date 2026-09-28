from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.models import User
from app.operators.summary_operator import SummaryOperator
from app.repositories.collaboration_repository import SqlAlchemyCollaborationRepository
from app.repositories.issue_repository import SqlAlchemyIssueRepository
from app.repositories.project_repository import SqlAlchemyProjectRepository
from app.repositories.view_notification_repository import SqlAlchemyViewNotificationRepository
from app.repositories.workspace_repository import SqlAlchemyWorkspaceRepository
from app.services.collaboration_service import CollaborationService, CollaborationValidationError
from app.services.issue_service import IssueService
from app.services.summary_service import SummaryService
from app.services.view_notification_service import ViewNotificationService
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        owner = User(email="owner@example.com", name="Owner", auth_issuer="issuer", auth_subject="owner", is_deleted=False, created_at=now, updated_at=now)
        teammate = User(email="team@example.com", name="Teammate", auth_issuer="issuer", auth_subject="team", is_deleted=False, created_at=now, updated_at=now)
        db.add_all([owner, teammate]); db.commit(); db.refresh(owner); db.refresh(teammate)
        workspace_repository = SqlAlchemyWorkspaceRepository(db)
        issue_repository = SqlAlchemyIssueRepository(db)
        project_repository = SqlAlchemyProjectRepository(db)
        view_repository = SqlAlchemyViewNotificationRepository(db)
        workspaces = WorkspaceService(workspace_repository)
        workspace, _ = workspaces.create_workspace(owner, name="CommonPlan", slug="commonplan", description=None)
        workspaces.put_workspace_member(owner, workspace.id, teammate.id, "member")
        team, _ = workspaces.create_team(owner, workspace.id, name="Core", issue_prefix="KEY", description=None)
        workspaces.put_team_member(owner, workspace.id, team.id, teammate.id, "member")
        issues = IssueService(issue_repository, workspaces)
        issue, _ = issues.create_issue(owner, workspace.id, team.id, title="Tracked", assignee_user_id=owner.id, label_ids=[])
        summary = SummaryService(SummaryOperator(issue_repository, project_repository, workspace_repository), workspaces)
        views = ViewNotificationService(view_repository, issue_repository, workspaces, summary)
        collaboration = CollaborationService(SqlAlchemyCollaborationRepository(db), workspaces, issues, views)
        yield views, collaboration, workspaces, owner, teammate, workspace, team, issue


def test_saved_team_view_executes_shared_filter_without_bypassing_access(context):
    views, _collaboration, workspaces, owner, teammate, workspace, team, issue = context
    view = views.create_view(owner, workspace.id, {
        "name": "My work", "team_id": team.id, "visibility": "team",
        "filter_spec": {"ownership": "mine", "timezone": "UTC"},
        "sort_by": "updated_at", "sort_direction": "desc",
    })

    assert views.list_views(teammate, workspace.id)[0].id == view.id
    assert views.execute_view(owner, workspace.id, view.id)[0]["key"] == issue.key

    workspaces.delete_team_member(owner, workspace.id, team.id, teammate.id)
    assert views.list_views(teammate, workspace.id) == []


def test_mentions_create_durable_inbox_items_and_removed_access_hides_them(context):
    views, collaboration, workspaces, owner, teammate, workspace, team, issue = context
    collaboration.create_comment(owner, workspace.id, issue.key, "Please review @Teammate", [teammate.id])

    inbox = views.inbox(teammate, workspace.id, unread_only=False)
    assert inbox["unread_count"] == 1
    notification = inbox["notifications"][0]
    assert notification.kind == "comment"

    views.mark_read(teammate, notification.id)
    assert views.inbox(teammate, workspace.id, unread_only=True)["notifications"] == []

    collaboration.create_comment(owner, workspace.id, issue.key, "Again @Teammate", [teammate.id])
    workspaces.delete_team_member(owner, workspace.id, team.id, teammate.id)
    assert views.inbox(teammate, workspace.id, unread_only=False)["notifications"] == []


def test_explicit_self_mention_creates_reminder_without_watcher_noise(context):
    views, collaboration, _workspaces, owner, _teammate, workspace, _team, issue = context

    collaboration.watch(owner, workspace.id, issue.key)
    collaboration.create_comment(owner, workspace.id, issue.key, "A normal watched comment")
    assert views.inbox(owner, workspace.id, unread_only=False)["notifications"] == []

    collaboration.create_comment(owner, workspace.id, issue.key, "@Owner remember this", [owner.id])
    inbox = views.inbox(owner, workspace.id, unread_only=False)

    assert inbox["unread_count"] == 1
    assert inbox["notifications"][0].kind == "self_mention"


def test_mentions_reject_users_outside_the_team(context):
    _views, collaboration, workspaces, owner, teammate, workspace, team, issue = context
    workspaces.delete_team_member(owner, workspace.id, team.id, teammate.id)

    with pytest.raises(CollaborationValidationError, match="Mentioned users must be active members"):
        collaboration.create_comment(owner, workspace.id, issue.key, "@Teammate", [teammate.id])
