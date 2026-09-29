from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import Notification, SavedView


class ViewNotificationRepository(Protocol):
    def views(self, workspace_id: str, user_id: int) -> list[SavedView]: ...
    def view(self, view_id: str) -> SavedView | None: ...
    def notifications(self, user_id: int, workspace_id: str | None, unread_only: bool) -> list[Notification]: ...
    def notification(self, notification_id: str) -> Notification | None: ...
    def unread_count(self, user_id: int, workspace_id: str | None) -> int: ...
    def add(self, record: object) -> None: ...
    def save_changes(self) -> None: ...
    def refresh(self, record: object) -> None: ...


class SqlAlchemyViewNotificationRepository:
    def __init__(self, db: Session): self.db = db

    def views(self, workspace_id: str, user_id: int) -> list[SavedView]:
        return list(self.db.scalars(
            select(SavedView).where(
                SavedView.workspace_id == workspace_id,
                SavedView.archived_at.is_(None),
                or_(SavedView.owner_user_id == user_id, SavedView.visibility.in_(["team", "workspace"])),
            ).order_by(SavedView.name, SavedView.id)
        ))

    def view(self, view_id: str) -> SavedView | None:
        return self.db.get(SavedView, view_id)

    def notifications(self, user_id: int, workspace_id: str | None, unread_only: bool) -> list[Notification]:
        stmt = select(Notification).where(Notification.recipient_user_id == user_id)
        if workspace_id: stmt = stmt.where(Notification.workspace_id == workspace_id)
        if unread_only: stmt = stmt.where(Notification.read_at.is_(None))
        return list(self.db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100)))

    def notification(self, notification_id: str) -> Notification | None:
        return self.db.get(Notification, notification_id)

    def unread_count(self, user_id: int, workspace_id: str | None) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.recipient_user_id == user_id, Notification.read_at.is_(None)
        )
        if workspace_id: stmt = stmt.where(Notification.workspace_id == workspace_id)
        return self.db.scalar(stmt) or 0

    def add(self, record: object) -> None: self.db.add(record)
    def save_changes(self) -> None: self.db.commit()
    def refresh(self, record: object) -> None: self.db.refresh(record)


def get_view_notification_repository(db: DbSession) -> ViewNotificationRepository:
    return SqlAlchemyViewNotificationRepository(db)


ViewNotificationRepositoryDep = Annotated[ViewNotificationRepository, Depends(get_view_notification_repository)]
