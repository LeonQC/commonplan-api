from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import CommentMention, Issue, IssueComment, IssueEvent, IssueWatcher, User


class CollaborationRepository(Protocol):
    def issue(self, workspace_id: str, key: str) -> Issue | None: ...
    def comment(self, comment_id: str) -> IssueComment | None: ...
    def children(self, issue_id: str) -> list[Issue]: ...
    def watcher(self, issue_id: str, user_id: int) -> IssueWatcher | None: ...
    def watchers(self, issue_id: str) -> list[tuple[IssueWatcher, User]]: ...
    def watcher_user_ids(self, issue_id: str) -> set[int]: ...
    def replace_mentions(self, comment_id: str, user_ids: set[int]) -> None: ...
    def add(self, record: object) -> None: ...
    def flush(self) -> None: ...
    def delete(self, record: object) -> None: ...
    def commit(self) -> None: ...
    def refresh(self, record: object) -> None: ...


class SqlAlchemyCollaborationRepository:
    def __init__(self, db: Session):
        self.db = db

    def issue(self, workspace_id: str, key: str) -> Issue | None:
        return self.db.scalar(select(Issue).where(Issue.workspace_id == workspace_id, Issue.key == key))

    def comment(self, comment_id: str) -> IssueComment | None:
        return self.db.get(IssueComment, comment_id)

    def children(self, issue_id: str) -> list[Issue]:
        return list(self.db.scalars(
            select(Issue)
            .where(Issue.parent_issue_id == issue_id, Issue.archived_at.is_(None))
            .order_by(Issue.position, Issue.id)
        ))

    def watcher(self, issue_id: str, user_id: int) -> IssueWatcher | None:
        return self.db.get(IssueWatcher, (issue_id, user_id))

    def watchers(self, issue_id: str) -> list[tuple[IssueWatcher, User]]:
        return list(self.db.execute(
            select(IssueWatcher, User)
            .join(User, User.id == IssueWatcher.user_id)
            .where(IssueWatcher.issue_id == issue_id)
            .order_by(User.name, User.id)
        ).all())

    def watcher_user_ids(self, issue_id: str) -> set[int]:
        return set(self.db.scalars(select(IssueWatcher.user_id).where(IssueWatcher.issue_id == issue_id)))

    def replace_mentions(self, comment_id: str, user_ids: set[int]) -> None:
        self.db.query(CommentMention).filter(CommentMention.comment_id == comment_id).delete(synchronize_session=False)
        for user_id in sorted(user_ids):
            self.db.add(CommentMention(comment_id=comment_id, user_id=user_id))

    def add(self, record: object) -> None:
        self.db.add(record)

    def flush(self) -> None:
        self.db.flush()

    def delete(self, record: object) -> None:
        self.db.delete(record)

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, record: object) -> None:
        self.db.refresh(record)


def get_collaboration_repository(db: DbSession) -> CollaborationRepository:
    return SqlAlchemyCollaborationRepository(db)


CollaborationRepositoryDep = Annotated[CollaborationRepository, Depends(get_collaboration_repository)]
