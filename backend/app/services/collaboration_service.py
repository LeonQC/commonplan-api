import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends

from app.models import IssueComment, IssueEvent, IssueWatcher, User
from app.repositories.collaboration_repository import CollaborationRepository, CollaborationRepositoryDep
from app.services.issue_service import IssueService, IssueServiceDep
from app.services.resource_policy import ResourceForbidden, ResourceNotFound, ResourcePolicy
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class CollaborationValidationError(Exception): pass


class CollaborationService:
    def __init__(
        self,
        repository: CollaborationRepository,
        workspaces: WorkspaceService,
        issues: IssueService,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.issues = issues
        self.policy = ResourcePolicy(workspaces)

    def create_comment(self, user: User, workspace_id: str, key: str, body: str):
        issue = self._issue(user, workspace_id, key)
        normalized = body.strip()
        if not normalized:
            raise CollaborationValidationError("Comment cannot be empty")
        comment = IssueComment(id=str(uuid.uuid4()), issue_id=issue.id, author_user_id=user.id, body=normalized)
        self.repository.add(comment)
        mentioned = self._mentioned_users(user, workspace_id, issue.team_id, normalized)
        self.repository.replace_mentions(comment.id, mentioned)
        self._ensure_watcher(issue.id, user.id, "participated")
        for user_id in mentioned:
            self._ensure_watcher(issue.id, user_id, "mentioned")
        self._event(issue.id, user.id, "comment.created", {"comment_id": comment.id, "mentioned_user_ids": sorted(mentioned)})
        self.repository.commit()
        self.repository.refresh(comment)
        return self._comment_activity(comment)

    def update_comment(self, user: User, workspace_id: str, key: str, comment_id: str, body: str):
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
        mentioned = self._mentioned_users(user, workspace_id, issue.team_id, normalized)
        self.repository.replace_mentions(comment.id, mentioned)
        for user_id in mentioned:
            self._ensure_watcher(issue.id, user_id, "mentioned")
        self._event(issue.id, user.id, "comment.updated", {"comment_id": comment.id, "mentioned_user_ids": sorted(mentioned)})
        self.repository.commit()
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
        self.repository.commit()

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
        self.repository.commit()
        return self.collaboration(user, workspace_id, key)

    def unwatch(self, user: User, workspace_id: str, key: str):
        issue = self._issue(user, workspace_id, key)
        watcher = self.repository.watcher(issue.id, user.id)
        if watcher is not None:
            self.repository.delete(watcher)
            self._event(issue.id, user.id, "watcher.removed", {"user_id": user.id})
            self.repository.commit()
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

    def _mentioned_users(self, user, workspace_id, team_id, body):
        members = self.workspaces.team_members(user, workspace_id, team_id)
        lowered = body.lower()
        return {member.id for member, _membership in members if f"@{member.email.lower()}" in lowered and member.id != user.id}

    def _ensure_watcher(self, issue_id, user_id, reason):
        if self.repository.watcher(issue_id, user_id) is None:
            self.repository.add(IssueWatcher(issue_id=issue_id, user_id=user_id, reason=reason))

    def _event(self, issue_id, actor_user_id, event_type, changes):
        self.repository.add(IssueEvent(
            id=str(uuid.uuid4()), issue_id=issue_id, actor_user_id=actor_user_id,
            event_type=event_type, changes={"schema_version": 1, **changes},
        ))

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
) -> CollaborationService:
    return CollaborationService(repository, workspaces, issues)


CollaborationServiceDep = Annotated[CollaborationService, Depends(get_collaboration_service)]
