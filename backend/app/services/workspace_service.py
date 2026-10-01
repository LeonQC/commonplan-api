import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends
from app.models import AuditEvent, IssueRelationType, Team, TeamCycleSettings, TeamMembership, User, WorkflowState, Workspace, WorkspaceInvitation, WorkspaceMembership, WorkspaceSettings
from app.repositories.errors import RepositoryConflictError
from app.repositories.workspace_repository import WorkspaceRepository, WorkspaceRepositoryDep


class WorkspaceNotFound(Exception):
    pass


class WorkspaceForbidden(Exception):
    pass


class WorkspaceConflict(Exception):
    pass


class WorkspaceValidationError(Exception):
    pass


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository

    def list_workspaces(self, user: User):
        return self.repository.workspaces_for_user(user.id)

    def create_workspace(self, user: User, *, name: str, slug: str, description: str | None):
        workspace = Workspace(
            id=str(uuid.uuid4()),
            name=name.strip(),
            slug=slug.lower(),
            description=description,
            created_by_user_id=user.id,
        )
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
        self.repository.add(workspace)
        # The relation types below reference the workspace directly. Flush the
        # aggregate root first so SQLite and PostgreSQL both observe the FK in
        # a deterministic order while keeping the transaction atomic.
        self.repository.flush()
        self.repository.add(membership)
        self.repository.add(WorkspaceSettings(workspace_id=workspace.id, updated_by_user_id=user.id))
        for key, forward_label, inverse_label, category, symmetric, allow_cycles in (
            ("blocked_by", "is blocked by", "blocks", "dependency", False, False),
            ("relates_to", "relates to", "relates to", "custom", True, True),
            ("action_item_of", "is an action item of", "has action item", "custom", False, True),
        ):
            self.repository.add(IssueRelationType(
                id=str(uuid.uuid4()), workspace_id=workspace.id, key=key,
                forward_label=forward_label, inverse_label=inverse_label,
                category=category, is_system=True, symmetric=symmetric,
                allow_cycles=allow_cycles,
            ))
        self._commit()
        self.repository.refresh(workspace)
        return workspace, membership

    def get_workspace(self, user: User, workspace_id: str):
        workspace, membership = self._require_workspace_member(user, workspace_id)
        return workspace, membership

    def update_workspace(self, user: User, workspace_id: str, changes: dict):
        workspace, membership = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(membership)
        for key in ("name", "description"):
            if key in changes:
                setattr(workspace, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
        self._audit(workspace_id, user.id, "workspace.updated", "workspace", workspace_id, {"fields": sorted(changes)})
        self._commit()
        self.repository.refresh(workspace)
        return workspace, membership

    def list_teams(self, user: User, workspace_id: str):
        _workspace, membership = self._require_workspace_member(user, workspace_id)
        include_all = membership.role in {"owner", "admin"}
        return self.repository.teams_for_user(workspace_id, user.id, include_all)

    def create_team(self, user: User, workspace_id: str, *, name: str, issue_prefix: str, description: str | None):
        _workspace, membership = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(membership)
        team = Team(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            name=name.strip(),
            issue_prefix=issue_prefix.upper(),
            description=description,
            next_issue_number=1,
        )
        team_membership = TeamMembership(team_id=team.id, user_id=user.id, role="lead")
        self.repository.add(team)
        self.repository.add(team_membership)
        self.repository.add(TeamCycleSettings(team_id=team.id, updated_by_user_id=user.id))
        for position, (state_name, category, is_default) in enumerate(
            [
                ("Backlog", "backlog", False),
                ("Todo", "todo", True),
                ("In Progress", "in_progress", False),
                ("Done", "done", False),
            ]
        ):
            self.repository.add(
                WorkflowState(
                    id=str(uuid.uuid4()),
                    team_id=team.id,
                    name=state_name,
                    category=category,
                    position=position,
                    is_default=is_default,
                )
            )
        self._commit()
        self.repository.refresh(team)
        return team, team_membership

    def get_team(self, user: User, workspace_id: str, team_id: str):
        workspace_membership = self._require_workspace_member(user, workspace_id)[1]
        team = self._team_in_workspace(team_id, workspace_id)
        team_membership = self.repository.team_membership(team_id, user.id)
        if workspace_membership.role not in {"owner", "admin"} and team_membership is None:
            raise WorkspaceForbidden
        return team, team_membership, workspace_membership

    def update_team(self, user: User, workspace_id: str, team_id: str, changes: dict):
        team, team_membership, workspace_membership = self.get_team(user, workspace_id, team_id)
        if workspace_membership.role not in {"owner", "admin"} and (
            team_membership is None or team_membership.role != "lead"
        ):
            raise WorkspaceForbidden
        for key in ("name", "description"):
            if key in changes:
                setattr(team, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
        self._commit()
        self.repository.refresh(team)
        return team, team_membership, workspace_membership

    def workspace_members(self, user: User, workspace_id: str):
        self._require_workspace_member(user, workspace_id)
        return self.repository.workspace_members(workspace_id)

    def put_workspace_member(self, user: User, workspace_id: str, target_user_id: int, role: str):
        _workspace, actor = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(actor)
        if role not in {"owner", "admin", "member"}:
            raise WorkspaceValidationError("Invalid workspace role")
        target_user = self.repository.user(target_user_id)
        if target_user is None or target_user.is_deleted:
            raise WorkspaceNotFound
        membership = self.repository.workspace_membership(workspace_id, target_user_id)
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=workspace_id, user_id=target_user_id, role=role, status="active"
            )
            self.repository.add(membership)
        else:
            if membership.role == "owner" and role != "owner":
                self._ensure_other_owner(workspace_id, target_user_id)
            membership.role = role
            membership.status = "active"
        self._audit(workspace_id, user.id, "workspace.member.updated", "user", str(target_user_id), {"role": role})
        self._commit()
        return target_user, membership

    def delete_workspace_member(self, user: User, workspace_id: str, target_user_id: int):
        _workspace, actor = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(actor)
        membership = self.repository.workspace_membership(workspace_id, target_user_id)
        if membership is None:
            raise WorkspaceNotFound
        if membership.role == "owner":
            self._ensure_other_owner(workspace_id, target_user_id)
        self.repository.delete_team_memberships_for_workspace(workspace_id, target_user_id)
        self.repository.delete(membership)
        self._audit(workspace_id, user.id, "workspace.member.removed", "user", str(target_user_id), {})
        self._commit()

    def workspace_settings(self, user: User, workspace_id: str):
        self._require_workspace_member(user, workspace_id)
        settings = self.repository.settings(workspace_id)
        if settings is None:
            settings = WorkspaceSettings(workspace_id=workspace_id, updated_by_user_id=user.id)
            self.repository.add(settings)
            self._commit()
            self.repository.refresh(settings)
        return settings

    def update_workspace_settings(self, user: User, workspace_id: str, changes: dict):
        _workspace, membership = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(membership)
        if changes.get("domain_policy") not in {None, "invite_only", "verified_domains"}:
            raise WorkspaceValidationError("Invalid domain policy")
        settings = self.workspace_settings(user, workspace_id)
        for key in ("allow_member_invites", "default_timezone", "domain_policy"):
            if key in changes and changes[key] is not None:
                setattr(settings, key, changes[key])
        settings.updated_by_user_id = user.id
        self._audit(workspace_id, user.id, "workspace.settings.updated", "workspace_settings", workspace_id, {"fields": sorted(changes)})
        self._commit()
        self.repository.refresh(settings)
        return settings

    def audit_events(self, user: User, workspace_id: str, limit: int = 100):
        _workspace, membership = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(membership)
        return self.repository.audit_events(workspace_id, min(max(limit, 1), 200))

    def team_members(self, user: User, workspace_id: str, team_id: str):
        self.get_team(user, workspace_id, team_id)
        return self.repository.team_members(team_id)

    def put_team_member(self, user: User, workspace_id: str, team_id: str, target_user_id: int, role: str):
        _team, actor_team, actor_workspace = self.get_team(user, workspace_id, team_id)
        if actor_workspace.role not in {"owner", "admin"} and (
            actor_team is None or actor_team.role != "lead"
        ):
            raise WorkspaceForbidden
        if role not in {"lead", "member"}:
            raise WorkspaceValidationError("Invalid team role")
        workspace_membership = self.repository.workspace_membership(workspace_id, target_user_id)
        if workspace_membership is None or workspace_membership.status != "active":
            raise WorkspaceValidationError("Team member must be an active workspace member")
        target_user = self.repository.user(target_user_id)
        membership = self.repository.team_membership(team_id, target_user_id)
        if membership is None:
            membership = TeamMembership(team_id=team_id, user_id=target_user_id, role=role)
            self.repository.add(membership)
        else:
            membership.role = role
        self._audit(workspace_id, user.id, "team.member.updated", "team_membership", f"{team_id}:{target_user_id}", {"team_id": team_id, "user_id": target_user_id, "role": role})
        self._commit()
        return target_user, membership

    def delete_team_member(self, user: User, workspace_id: str, team_id: str, target_user_id: int):
        _team, actor_team, actor_workspace = self.get_team(user, workspace_id, team_id)
        if actor_workspace.role not in {"owner", "admin"} and (
            actor_team is None or actor_team.role != "lead"
        ):
            raise WorkspaceForbidden
        membership = self.repository.team_membership(team_id, target_user_id)
        if membership is None:
            raise WorkspaceNotFound
        self.repository.delete(membership)
        self._audit(workspace_id, user.id, "team.member.removed", "team_membership", f"{team_id}:{target_user_id}", {"team_id": team_id, "user_id": target_user_id})
        self._commit()

    def create_invitation(self, user: User, workspace_id: str, *, email: str, role: str, team_id: str | None):
        _workspace, membership = self._require_workspace_member(user, workspace_id)
        self._require_workspace_admin(membership)
        if role not in {"admin", "member"}:
            raise WorkspaceValidationError("Invalid invitation role")
        if team_id is not None:
            self._team_in_workspace(team_id, workspace_id)
        raw_token = secrets.token_urlsafe(32)
        invitation = WorkspaceInvitation(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            email=email.strip().lower(),
            role=role,
            team_id=team_id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            invited_by_user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self.repository.add(invitation)
        self._audit(workspace_id, user.id, "workspace.invitation.created", "workspace_invitation", invitation.id, {"email": invitation.email, "role": role, "team_id": team_id})
        self._commit()
        self.repository.refresh(invitation)
        return invitation, raw_token

    def accept_invitation(self, user: User, token: str):
        invitation = self.repository.invitation_by_hash(hashlib.sha256(token.encode()).hexdigest())
        now = datetime.now(timezone.utc)
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or self._aware(invitation.expires_at) <= now
        ):
            raise WorkspaceNotFound
        if invitation.email.lower() != user.email.lower():
            raise WorkspaceForbidden
        membership = self.repository.workspace_membership(invitation.workspace_id, user.id)
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=invitation.workspace_id,
                user_id=user.id,
                role=invitation.role,
                status="active",
            )
            self.repository.add(membership)
        if invitation.team_id and self.repository.team_membership(invitation.team_id, user.id) is None:
            self.repository.add(TeamMembership(team_id=invitation.team_id, user_id=user.id, role="member"))
        invitation.accepted_at = now
        self._commit()
        return self.get_workspace(user, invitation.workspace_id)

    def _require_workspace_member(self, user: User, workspace_id: str):
        workspace = self.repository.workspace(workspace_id)
        if workspace is None or workspace.archived_at is not None:
            raise WorkspaceNotFound
        membership = self.repository.workspace_membership(workspace_id, user.id)
        if membership is None or membership.status != "active":
            raise WorkspaceForbidden
        return workspace, membership

    @staticmethod
    def _require_workspace_admin(membership: WorkspaceMembership):
        if membership.role not in {"owner", "admin"}:
            raise WorkspaceForbidden

    def _team_in_workspace(self, team_id: str, workspace_id: str) -> Team:
        team = self.repository.team(team_id)
        if team is None or team.workspace_id != workspace_id or team.archived_at is not None:
            raise WorkspaceNotFound
        return team

    def _ensure_other_owner(self, workspace_id: str, excluded_user_id: int):
        count = self.repository.other_active_owner_count(workspace_id, excluded_user_id)
        if not count:
            raise WorkspaceValidationError("Workspace must keep an active owner")

    def _audit(self, workspace_id, actor_user_id, action, target_type, target_id, details):
        self.repository.add(AuditEvent(
            id=str(uuid.uuid4()), workspace_id=workspace_id, actor_user_id=actor_user_id,
            action=action, target_type=target_type, target_id=target_id, details=details,
        ))

    def _commit(self):
        try:
            self.repository.save_changes()
        except RepositoryConflictError as exc:
            raise WorkspaceConflict from exc

    def is_team_member(self, team_id: str, user_id: int) -> bool:
        return self.repository.team_membership(team_id, user_id) is not None

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_workspace_service(repository: WorkspaceRepositoryDep) -> WorkspaceService:
    return WorkspaceService(repository)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
