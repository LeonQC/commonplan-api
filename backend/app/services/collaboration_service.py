import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends

from app.models import IssueComment, IssueEvent, IssueWatcher, User
from app.repositories.collaboration_repository import CollaborationRepository, CollaborationRepositoryDep
from app.services.issue_service import IssueService, IssueServiceDep
from app.services.resource_policy import ResourceForbidden, ResourceNotFound, ResourcePolicy
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep
from app.services.view_notification_service import ViewNotificationService, ViewNotificationServiceDep


class CollaborationValidationError(Exception): pass


class CollaborationService:
    def __init__(
        self,
        repository: CollaborationRepository,
        workspaces: WorkspaceService,
        issues: IssueService,
        notifications: ViewNotificationService | None = None,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.issues = issues
        self.notifications = notifications
        self.policy = ResourcePolicy(workspaces)

    def create_comment(self, user: User, workspace_id: str, key: str, body: str, mentioned_user_ids: list[int] | None = None):
        issue = self._issue(user, workspace_id, key)
        normalized = body.strip()
        if not normalized:
            raise CollaborationValidationError("Comment cannot be empty")
        comment = IssueComment(id=str(uuid.uuid4()), issue_id=issue.id, author_user_id=user.id, body=normalized)
        self.repository.add(comment)
        # CommentMention has no ORM relationship to advertise insert ordering, so
        # persist the parent row before adding its foreign-key children.
        self.repository.flush()
        mentioned = self._mentioned_users(user, workspace_id, issue.team_id, mentioned_user_ids or [])
        self.repository.replace_mentions(comment.id, mentioned)
        self._ensure_watcher(issue.id, user.id, "participated")
        for user_id in mentioned:
            self._ensure_watcher(issue.id, user_id, "mentioned")
        event_id = self._event(issue.id, user.id, "comment.created", {"comment_id": comment.id, "mentioned_user_ids": sorted(mentioned)})
        self._notify(issue, event_id, user.id, "comment", mentioned, {"issue_key": issue.key, "comment_id": comment.id})
        self.repository.save_changes()
        self.repository.refresh(comment)
        return self._comment_activity(comment)

    def update_comment(self, user: User, workspace_id: str, key: str, comment_id: str, body: str, mentioned_user_ids: list[int] | None = None):
        issue = self._issue(user, workspace_id, key)
        comment = self.repository.comment(comment_id)
        if comment is None or comment.issue_id != issue.id or comment.deleted_at is not None:
            raise ResourceNotFound
        self.policy.require_comment_manager(user, workspace_id, issue, comment)
        normalized = body.strip()
        if not normalized:
            raise CollaborationValidationError("Comment cannot be empty")
        comment.body = normalized
        comment.edited_at = datetime.now(timezone.utc)
        mentioned = self._mentioned_users(user, workspace_id, issue.team_id, mentioned_user_ids or [])
        self.repository.replace_mentions(comment.id, mentioned)
        for user_id in mentioned:
            self._ensure_watcher(issue.id, user_id, "mentioned")
        event_id = self._event(issue.id, user.id, "comment.updated", {"comment_id": comment.id, "mentioned_user_ids": sorted(mentioned)})
        self._notify(issue, event_id, user.id, "comment_updated", mentioned, {"issue_key": issue.key, "comment_id": comment.id})
        self.repository.save_changes()
        self.repository.refresh(comment)
        return self._comment_activity(comment)

    def delete_comment(self, user: User, workspace_id: str, key: str, comment_id: str):
        issue = self._issue(user, workspace_id, key)
        comment = self.repository.comment(comment_id)
        if comment is None or comment.issue_id != issue.id or comment.deleted_at is not None:
            raise ResourceNotFound
        self.policy.require_comment_manager(user, workspace_id, issue, comment)
        comment.deleted_at = datetime.now(timezone.utc)
        self.repository.replace_mentions(comment.id, set())
        self._event(issue.id, user.id, "comment.deleted", {"comment_id": comment.id})
        self.repository.save_changes()

    def collaboration(self, user: User, workspace_id: str, key: str):
        issue = self._issue(user, workspace_id, key)
        return {
            "watching": self.repository.watcher(issue.id, user.id) is not None,
            "watchers": self.repository.watchers(issue.id),
            "children": self.repository.children(issue.id),
        }

    def watch(self, user: User, workspace_id: str, key: str):
        issue = self._issue(user, workspace_id, key)
        self._ensure_watcher(issue.id, user.id, "manual")
        self._event(issue.id, user.id, "watcher.added", {"user_id": user.id})
        self.repository.save_changes()
        return self.collaboration(user, workspace_id, key)

    def unwatch(self, user: User, workspace_id: str, key: str):
        issue = self._issue(user, workspace_id, key)
        watcher = self.repository.watcher(issue.id, user.id)
        if watcher is not None:
            self.repository.delete(watcher)
            self._event(issue.id, user.id, "watcher.removed", {"user_id": user.id})
            self.repository.save_changes()
        return self.collaboration(user, workspace_id, key)

    def create_sub_issue(self, user: User, workspace_id: str, key: str, values: dict):
        parent = self._issue(user, workspace_id, key)
        return self.issues.create_issue(
            user,
            workspace_id,
            parent.team_id,
            **values,
            parent_issue_id=parent.id,
        )

    def _issue(self, user, workspace_id, key):
        issue = self.repository.issue(workspace_id, key.upper())
        self.policy.require_issue_access(user, workspace_id, issue)
        return issue

    def _mentioned_users(self, user, workspace_id, team_id, mentioned_user_ids):
        members = self.workspaces.team_members(user, workspace_id, team_id)
        member_ids = {member.id for member, _membership in members}
        mentioned = set(mentioned_user_ids)
        if not mentioned.issubset(member_ids):
            raise CollaborationValidationError("Mentioned users must be active members of this team")
        return mentioned

    def _ensure_watcher(self, issue_id, user_id, reason):
        if self.repository.watcher(issue_id, user_id) is None:
            self.repository.add(IssueWatcher(issue_id=issue_id, user_id=user_id, reason=reason))

    def _event(self, issue_id, actor_user_id, event_type, changes):
        event_id = str(uuid.uuid4())
        self.repository.add(IssueEvent(
            id=event_id, issue_id=issue_id, actor_user_id=actor_user_id,
            event_type=event_type, changes={"schema_version": 1, **changes},
        ))
        return event_id

    def _notify(self, issue, event_id, actor_user_id, kind, mentioned, payload):
        if self.notifications is None:
            return
        recipients = (self.repository.watcher_user_ids(issue.id) | set(mentioned)) - {actor_user_id}
        self.notifications.enqueue_many(
            recipients=recipients, workspace_id=issue.workspace_id, issue_id=issue.id,
            event_id=event_id, actor_user_id=actor_user_id, kind=kind, payload=payload,
        )
        if actor_user_id in mentioned:
            self.notifications.enqueue_many(
                recipients={actor_user_id}, workspace_id=issue.workspace_id, issue_id=issue.id,
                event_id=event_id, actor_user_id=actor_user_id, kind="self_mention", payload=payload,
                include_actor=True,
            )

    def _comment_activity(self, comment):
        return {
            "id": comment.id, "kind": "comment", "actor_user_id": comment.author_user_id,
            "actor_name": None, "body": comment.body, "event_type": None, "changes": {},
            "created_at": comment.created_at, "edited_at": comment.edited_at,
        }


def get_collaboration_service(
    repository: CollaborationRepositoryDep,
    workspaces: WorkspaceServiceDep,
    issues: IssueServiceDep,
    notifications: ViewNotificationServiceDep,
) -> CollaborationService:
    return CollaborationService(repository, workspaces, issues, notifications)


CollaborationServiceDep = Annotated[CollaborationService, Depends(get_collaboration_service)]
