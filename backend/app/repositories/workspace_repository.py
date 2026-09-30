from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import (
    AuditEvent,
    Team,
    TeamMembership,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
    WorkspaceSettings,
)
from app.repositories.errors import RepositoryConflictError


class WorkspaceRepository(Protocol):
    def workspace(self, workspace_id: str) -> Workspace | None: ...
    def workspace_by_slug(self, slug: str) -> Workspace | None: ...
    def workspace_membership(self, workspace_id: str, user_id: int) -> WorkspaceMembership | None: ...
    def workspaces_for_user(self, user_id: int) -> list[tuple[Workspace, WorkspaceMembership]]: ...
    def team(self, team_id: str) -> Team | None: ...
    def team_membership(self, team_id: str, user_id: int) -> TeamMembership | None: ...
    def teams_for_user(self, workspace_id: str, user_id: int, include_all: bool) -> list[tuple[Team, TeamMembership | None]]: ...
    def workspace_members(self, workspace_id: str) -> list[tuple[User, WorkspaceMembership]]: ...
    def team_members(self, team_id: str) -> list[tuple[User, TeamMembership]]: ...
    def user(self, user_id: int) -> User | None: ...
    def delete_team_memberships_for_workspace(self, workspace_id: str, user_id: int) -> None: ...
    def other_active_owner_count(self, workspace_id: str, excluded_user_id: int) -> int: ...
    def invitation_by_hash(self, token_hash: str) -> WorkspaceInvitation | None: ...
    def settings(self, workspace_id: str) -> WorkspaceSettings | None: ...
    def audit_events(self, workspace_id: str, limit: int = 100) -> list[AuditEvent]: ...
    def add(self, record: object) -> None: ...
    def flush(self) -> None: ...
    def delete(self, record: object) -> None: ...
    def save_changes(self) -> None: ...
    def refresh(self, record: object) -> None: ...


class SqlAlchemyWorkspaceRepository:
    def __init__(self, db: Session):
        self.db = db

    def workspace(self, workspace_id: str) -> Workspace | None:
        return self.db.get(Workspace, workspace_id)

    def workspace_by_slug(self, slug: str) -> Workspace | None:
        return self.db.scalar(select(Workspace).where(Workspace.slug == slug))

    def workspace_membership(self, workspace_id: str, user_id: int) -> WorkspaceMembership | None:
        return self.db.get(WorkspaceMembership, (workspace_id, user_id))

    def workspaces_for_user(self, user_id: int) -> list[tuple[Workspace, WorkspaceMembership]]:
        stmt = (
            select(Workspace, WorkspaceMembership)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
                Workspace.archived_at.is_(None),
            )
            .order_by(Workspace.name, Workspace.id)
        )
        return list(self.db.execute(stmt).all())

    def team(self, team_id: str) -> Team | None:
        return self.db.get(Team, team_id)

    def team_membership(self, team_id: str, user_id: int) -> TeamMembership | None:
        return self.db.get(TeamMembership, (team_id, user_id))

    def teams_for_user(self, workspace_id: str, user_id: int, include_all: bool) -> list[tuple[Team, TeamMembership | None]]:
        stmt = select(Team, TeamMembership).outerjoin(
            TeamMembership,
            (TeamMembership.team_id == Team.id) & (TeamMembership.user_id == user_id),
        ).where(Team.workspace_id == workspace_id, Team.archived_at.is_(None))
        if not include_all:
            stmt = stmt.where(TeamMembership.user_id == user_id)
        return list(self.db.execute(stmt.order_by(Team.name, Team.id)).all())

    def workspace_members(self, workspace_id: str) -> list[tuple[User, WorkspaceMembership]]:
        stmt = (
            select(User, WorkspaceMembership)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(User.name, User.id)
        )
        return list(self.db.execute(stmt).all())

    def team_members(self, team_id: str) -> list[tuple[User, TeamMembership]]:
        stmt = (
            select(User, TeamMembership)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(TeamMembership.team_id == team_id)
            .order_by(User.name, User.id)
        )
        return list(self.db.execute(stmt).all())

    def user(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def delete_team_memberships_for_workspace(self, workspace_id: str, user_id: int) -> None:
        team_ids = select(Team.id).where(Team.workspace_id == workspace_id)
        self.db.query(TeamMembership).filter(
            TeamMembership.user_id == user_id,
            TeamMembership.team_id.in_(team_ids),
        ).delete(synchronize_session=False)

    def other_active_owner_count(self, workspace_id: str, excluded_user_id: int) -> int:
        return self.db.scalar(
            select(func.count()).select_from(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == "owner",
                WorkspaceMembership.status == "active",
                WorkspaceMembership.user_id != excluded_user_id,
            )
        ) or 0

    def invitation_by_hash(self, token_hash: str) -> WorkspaceInvitation | None:
        return self.db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == token_hash))

    def settings(self, workspace_id: str) -> WorkspaceSettings | None:
        return self.db.get(WorkspaceSettings, workspace_id)

    def audit_events(self, workspace_id: str, limit: int = 100) -> list[AuditEvent]:
        return list(self.db.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        ))

    def add(self, record: object) -> None:
        self.db.add(record)

    def flush(self) -> None:
        self.db.flush()

    def delete(self, record: object) -> None:
        self.db.delete(record)

    def save_changes(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RepositoryConflictError from exc

    def refresh(self, record: object) -> None:
        self.db.refresh(record)


def get_workspace_repository(db: DbSession) -> WorkspaceRepository:
    return SqlAlchemyWorkspaceRepository(db)


WorkspaceRepositoryDep = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]
