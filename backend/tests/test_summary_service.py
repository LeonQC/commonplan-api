from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import User
from app.operators.summary_operator import SummaryOperator
from app.repositories.issue_repository import SqlAlchemyIssueRepository
from app.repositories.project_repository import SqlAlchemyProjectRepository
from app.repositories.workspace_repository import SqlAlchemyWorkspaceRepository
from app.services.issue_service import IssueService
from app.services.project_service import ProjectService
from app.services.summary_service import SummaryService, SummaryValidationError
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        owner = User(email="owner@example.com", name="Owner", auth_issuer="issuer", auth_subject="owner", is_deleted=False, created_at=now, updated_at=now)
        teammate = User(email="team@example.com", name="Teammate", auth_issuer="issuer", auth_subject="team", is_deleted=False, created_at=now, updated_at=now)
        db.add_all([owner, teammate])
        db.commit()
        db.refresh(owner)
        db.refresh(teammate)
        workspace_repository = SqlAlchemyWorkspaceRepository(db)
        issue_repository = SqlAlchemyIssueRepository(db)
        project_repository = SqlAlchemyProjectRepository(db)
        workspaces = WorkspaceService(workspace_repository)
        workspace, _ = workspaces.create_workspace(owner, name="CommonPlan", slug="commonplan", description=None)
        workspaces.put_workspace_member(owner, workspace.id, teammate.id, "member")
        team, _ = workspaces.create_team(owner, workspace.id, name="Core", issue_prefix="KEY", description=None)
        workspaces.put_team_member(owner, workspace.id, team.id, teammate.id, "member")
        issues = IssueService(issue_repository, workspaces)
        projects = ProjectService(project_repository, workspaces)
        summary = SummaryService(
            SummaryOperator(issue_repository, project_repository, workspace_repository),
            workspaces,
        )
        yield summary, issues, projects, workspaces, owner, teammate, workspace, team


def test_team_summary_uses_one_filter_scope_for_all_metrics(context):
    summary, issues, projects, _workspaces, owner, teammate, workspace, team = context
    project = projects.create_project(owner, workspace.id, team.id, name="Launch", status="in_progress")["project"]
    cycle = issues.create_cycle(owner, workspace.id, team.id, name="Cycle 1", starts_on=date.today() - timedelta(days=2), ends_on=date.today() + timedelta(days=12))
    todo = next(state for state in issues.states(owner, workspace.id, team.id) if state.category == "todo")
    done = next(state for state in issues.states(owner, workspace.id, team.id) if state.category == "done")
    first, _ = issues.create_issue(owner, workspace.id, team.id, title="Urgent launch item", priority=4, assignee_user_id=teammate.id, project_id=project.id, cycle_id=cycle.id, due_date=date.today() - timedelta(days=1), label_ids=[])
    second, _ = issues.create_issue(owner, workspace.id, team.id, title="Completed launch item", project_id=project.id, cycle_id=cycle.id, label_ids=[])
    issues.update_issue(owner, workspace.id, second.key, {"version": 1, "workflow_state_id": done.id})

    result = summary.team_summary(owner, workspace.id, team.id, {"project": [project.id], "timezone": "UTC"})

    assert result["headline_metrics"] == {"total": 2, "open": 1, "in_progress": 0, "completed": 1, "overdue": 1, "unassigned": 0}
    assert next(row for row in result["status_distribution"] if row["category"] == "todo")["count"] == 1
    assert next(row for row in result["priority_distribution"] if row["priority"] == 4)["count"] == 1
    assert result["cycle_progress"]["percent"] == 50
    assert result["project_distribution"][0]["percent"] == 50
    assert [row["key"] for row in result["attention_issues"]["overdue"]] == [first.key]
    assert len(result["matching_issues"]) == 2

    mine = summary.team_summary(teammate, workspace.id, team.id, {"ownership": "mine", "timezone": "UTC"})
    assert mine["headline_metrics"]["total"] == 1
    assert mine["matching_issues"][0]["key"] == first.key
    assert todo.id == first.workflow_state_id


def test_summary_rejects_cross_team_filter_references(context):
    summary, issues, projects, workspaces, owner, _teammate, workspace, team = context
    second_team, _ = workspaces.create_team(owner, workspace.id, name="Platform", issue_prefix="PLAT", description=None)
    foreign_project = projects.create_project(owner, workspace.id, second_team.id, name="Foreign", status="planned")["project"]

    with pytest.raises(SummaryValidationError):
        summary.team_summary(owner, workspace.id, team.id, {"project": [foreign_project.id], "timezone": "UTC"})

    with pytest.raises(SummaryValidationError):
        summary.team_summary(owner, workspace.id, team.id, {"status": ["unknown"], "timezone": "UTC"})


def test_summary_layers_depend_only_on_repository_interfaces():
    class EmptyIssues:
        def states(self, _team_id): return []
        def cycles(self, _team_id): return []
        def labels(self, _team_id): return []
        def recently_updated_issues(self, _team_id, *, include_archived=False): return []
        def issue_label_pairs(self, _issue_ids): return []
        def events_for_issues(self, _issue_ids, *, event_type=None, limit=None): return []
        def comments_for_issues(self, _issue_ids, *, limit=None): return []
        def users(self, _user_ids): return []

    class EmptyProjects:
        def projects(self, _team_id): return []

    class EmptyWorkspaces:
        def team_members(self, _team_id): return []
        def get_team(self, _user, _workspace_id, _team_id): return object()

    now = datetime.now(timezone.utc)
    user = User(id=1, email="owner@example.com", name="Owner", auth_issuer="issuer", auth_subject="owner", is_deleted=False, created_at=now, updated_at=now)
    repositories = EmptyIssues(), EmptyProjects(), EmptyWorkspaces()
    operator = SummaryOperator(*repositories)
    summary = SummaryService(operator, repositories[2])

    result = summary.team_summary(user, "workspace", "team", {"timezone": "UTC"})

    assert result["headline_metrics"]["total"] == 0
    assert not hasattr(operator, "db")
    assert not hasattr(summary, "db")
