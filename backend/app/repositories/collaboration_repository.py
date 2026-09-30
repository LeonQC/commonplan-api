from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import CommentMention, Issue, IssueComment, IssueEvent, IssueRelation, IssueRelationType, IssueWatcher, User


class CollaborationRepository(Protocol):
    def issue(self, workspace_id: str, key: str) -> Issue | None: ...
    def issue_by_id(self, issue_id: str) -> Issue | None: ...
    def comment(self, comment_id: str) -> IssueComment | None: ...
    def children(self, issue_id: str) -> list[Issue]: ...
    def relation_types(self, workspace_id: str) -> list[IssueRelationType]: ...
    def relation_type(self, relation_type_id: str) -> IssueRelationType | None: ...
    def relations_for_issue(self, issue_id: str) -> list[IssueRelation]: ...
    def relations_for_team(self, team_id: str) -> list[IssueRelation]: ...
    def relation(self, relation_id: str) -> IssueRelation | None: ...
    def relation_pairs(self, relation_type_id: str) -> list[tuple[str, str]]: ...
    def watcher(self, issue_id: str, user_id: int) -> IssueWatcher | None: ...
    def watchers(self, issue_id: str) -> list[tuple[IssueWatcher, User]]: ...
    def watcher_user_ids(self, issue_id: str) -> set[int]: ...
    def replace_mentions(self, comment_id: str, user_ids: set[int]) -> None: ...
    def add(self, record: object) -> None: ...
    def flush(self) -> None: ...
    def delete(self, record: object) -> None: ...
    def save_changes(self) -> None: ...
    def refresh(self, record: object) -> None: ...


class SqlAlchemyCollaborationRepository:
    def __init__(self, db: Session):
        self.db = db

    def issue(self, workspace_id: str, key: str) -> Issue | None:
        return self.db.scalar(select(Issue).where(Issue.workspace_id == workspace_id, Issue.key == key))

    def issue_by_id(self, issue_id: str) -> Issue | None:
        return self.db.get(Issue, issue_id)

    def comment(self, comment_id: str) -> IssueComment | None:
        return self.db.get(IssueComment, comment_id)

    def children(self, issue_id: str) -> list[Issue]:
        return list(self.db.scalars(
            select(Issue)
            .where(Issue.parent_issue_id == issue_id, Issue.archived_at.is_(None))
            .order_by(Issue.position, Issue.id)
        ))

    def relation_types(self, workspace_id: str) -> list[IssueRelationType]:
        return list(self.db.scalars(
            select(IssueRelationType)
            .where(IssueRelationType.workspace_id == workspace_id, IssueRelationType.archived_at.is_(None))
            .order_by(IssueRelationType.is_system.desc(), IssueRelationType.forward_label, IssueRelationType.id)
        ))

    def relation_type(self, relation_type_id: str) -> IssueRelationType | None:
        return self.db.get(IssueRelationType, relation_type_id)

    def relations_for_issue(self, issue_id: str) -> list[IssueRelation]:
        return list(self.db.scalars(
            select(IssueRelation)
            .where((IssueRelation.source_issue_id == issue_id) | (IssueRelation.target_issue_id == issue_id))
            .order_by(IssueRelation.created_at, IssueRelation.id)
        ))

    def relations_for_team(self, team_id: str) -> list[IssueRelation]:
        team_issue_ids = select(Issue.id).where(
            Issue.team_id == team_id,
            Issue.archived_at.is_(None),
        )
        return list(self.db.scalars(
            select(IssueRelation)
            .where(
                (IssueRelation.source_issue_id.in_(team_issue_ids))
                | (IssueRelation.target_issue_id.in_(team_issue_ids))
            )
            .order_by(IssueRelation.created_at, IssueRelation.id)
        ))

    def relation(self, relation_id: str) -> IssueRelation | None:
        return self.db.get(IssueRelation, relation_id)

    def relation_pairs(self, relation_type_id: str) -> list[tuple[str, str]]:
        return list(self.db.execute(
            select(IssueRelation.source_issue_id, IssueRelation.target_issue_id)
            .where(IssueRelation.relation_type_id == relation_type_id)
        ).all())

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

    def save_changes(self) -> None:
        self.db.commit()

    def refresh(self, record: object) -> None:
        self.db.refresh(record)


def get_collaboration_repository(db: DbSession) -> CollaborationRepository:
    return SqlAlchemyCollaborationRepository(db)


CollaborationRepositoryDep = Annotated[CollaborationRepository, Depends(get_collaboration_repository)]
