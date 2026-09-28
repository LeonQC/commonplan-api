import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends

from app.models import Notification, SavedView, User
from app.repositories.issue_repository import IssueRepository, IssueRepositoryDep
from app.repositories.view_notification_repository import ViewNotificationRepository, ViewNotificationRepositoryDep
from app.services.summary_service import SummaryService, SummaryServiceDep, SummaryValidationError
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class ViewNotificationNotFound(Exception): pass
class ViewNotificationForbidden(Exception): pass
class ViewNotificationValidationError(Exception): pass


class ViewNotificationService:
    def __init__(self, repository: ViewNotificationRepository, issues: IssueRepository, workspaces: WorkspaceService, summary: SummaryService):
        self.repository = repository
        self.issues = issues
        self.workspaces = workspaces
        self.summary = summary

    def list_views(self, user: User, workspace_id: str):
        self.workspaces.get_workspace(user, workspace_id)
        visible = []
        for view in self.repository.views(workspace_id, user.id):
            try:
                self._require_view_access(user, view)
                visible.append(view)
            except (ViewNotificationNotFound, ViewNotificationForbidden):
                continue
        return visible

    def create_view(self, user: User, workspace_id: str, values: dict):
        self.workspaces.get_workspace(user, workspace_id)
        self._validate_view(user, workspace_id, values)
        view = SavedView(
            id=str(uuid.uuid4()), workspace_id=workspace_id, owner_user_id=user.id,
            team_id=values.get("team_id"), name=values["name"].strip(), visibility=values.get("visibility", "private"),
            filter_version=1, filter_spec=values.get("filter_spec") or {}, group_by=values.get("group_by"),
            sort_by=values.get("sort_by", "updated_at"), sort_direction=values.get("sort_direction", "desc"),
        )
        self.repository.add(view)
        self.repository.commit()
        self.repository.refresh(view)
        return view

    def update_view(self, user: User, workspace_id: str, view_id: str, changes: dict):
        view = self._view(user, workspace_id, view_id, manage=True)
        proposed = {"team_id": view.team_id, "visibility": view.visibility, "filter_spec": view.filter_spec, "sort_by": view.sort_by, "sort_direction": view.sort_direction, **changes}
        self._validate_view(user, workspace_id, proposed)
        for key, value in changes.items():
            setattr(view, key, value.strip() if key == "name" else value)
        self.repository.commit()
        self.repository.refresh(view)
        return view

    def archive_view(self, user: User, workspace_id: str, view_id: str):
        view = self._view(user, workspace_id, view_id, manage=True)
        view.archived_at = datetime.now(timezone.utc)
        self.repository.commit()

    def execute_view(self, user: User, workspace_id: str, view_id: str):
        view = self._view(user, workspace_id, view_id)
        if view.team_id is None:
            raise ViewNotificationValidationError("Saved issue views must select a team")
        return self.summary.team_summary(user, workspace_id, view.team_id, view.filter_spec)["matching_issues"]

    def inbox(self, user: User, workspace_id: str | None, unread_only: bool):
        if workspace_id: self.workspaces.get_workspace(user, workspace_id)
        visible = []
        for notification in self.repository.notifications(user.id, workspace_id, unread_only):
            if self._notification_visible(user, notification): visible.append(notification)
        return {"unread_count": sum(row.read_at is None for row in visible), "notifications": visible}

    def mark_read(self, user: User, notification_id: str):
        notification = self.repository.notification(notification_id)
        if notification is None or notification.recipient_user_id != user.id or not self._notification_visible(user, notification):
            raise ViewNotificationNotFound
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            self.repository.commit()
            self.repository.refresh(notification)
        return notification

    def enqueue_many(self, *, recipients: set[int], workspace_id: str, issue_id: str, event_id: str, actor_user_id: int, kind: str, payload: dict, include_actor: bool = False):
        effective_recipients = recipients if include_actor else recipients - {actor_user_id}
        for recipient in sorted(effective_recipients):
            self.repository.add(Notification(
                id=str(uuid.uuid4()), recipient_user_id=recipient, workspace_id=workspace_id,
                issue_id=issue_id, issue_event_id=event_id, actor_user_id=actor_user_id,
                kind=kind, payload=payload, dedupe_key=f"{event_id}:{recipient}:{kind}",
            ))

    def _view(self, user, workspace_id, view_id, manage=False):
        view = self.repository.view(view_id)
        if view is None or view.workspace_id != workspace_id or view.archived_at is not None: raise ViewNotificationNotFound
        self._require_view_access(user, view)
        if manage and view.owner_user_id != user.id:
            _workspace, membership = self.workspaces.get_workspace(user, workspace_id)
            if membership.role not in {"owner", "admin"}: raise ViewNotificationForbidden
        return view

    def _require_view_access(self, user, view):
        if view.visibility == "private" and view.owner_user_id != user.id: raise ViewNotificationNotFound
        if view.team_id:
            try: self.workspaces.get_team(user, view.workspace_id, view.team_id)
            except Exception as exc: raise ViewNotificationNotFound from exc
        else:
            try: self.workspaces.get_workspace(user, view.workspace_id)
            except Exception as exc: raise ViewNotificationNotFound from exc

    def _validate_view(self, user, workspace_id, values):
        visibility = values.get("visibility", "private")
        if visibility not in {"private", "team", "workspace"}: raise ViewNotificationValidationError("Invalid view visibility")
        team_id = values.get("team_id")
        if visibility == "team" and not team_id: raise ViewNotificationValidationError("Team views require a team")
        if team_id: self.workspaces.get_team(user, workspace_id, team_id)
        if values.get("sort_by", "updated_at") not in {"updated_at", "created_at", "priority", "due_date"}: raise ViewNotificationValidationError("Invalid view sort")
        if values.get("sort_direction", "desc") not in {"asc", "desc"}: raise ViewNotificationValidationError("Invalid sort direction")
        try: SummaryService._normalize_filters(values.get("filter_spec") or {})
        except SummaryValidationError as exc: raise ViewNotificationValidationError(str(exc)) from exc

    def _notification_visible(self, user, notification):
        if notification.issue_id is None:
            try: self.workspaces.get_workspace(user, notification.workspace_id); return True
            except Exception: return False
        issue = self.issues.issue_by_id(notification.issue_id)
        if issue is None: return False
        try: self.workspaces.get_team(user, notification.workspace_id, issue.team_id); return True
        except Exception: return False


def get_view_notification_service(
    repository: ViewNotificationRepositoryDep,
    issues: IssueRepositoryDep,
    workspaces: WorkspaceServiceDep,
    summary: SummaryServiceDep,
) -> ViewNotificationService:
    return ViewNotificationService(repository, issues, workspaces, summary)


ViewNotificationServiceDep = Annotated[ViewNotificationService, Depends(get_view_notification_service)]
