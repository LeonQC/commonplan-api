from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import (
    GitHubPullRequest,
    GitHubWebhookDelivery,
    Issue,
    IssuePullRequestLink,
    Team,
    Workspace,
)
from app.repositories.errors import RepositoryConflictError


class GitHubRepository(Protocol):
    def workspace_exists(self, workspace_id: str) -> bool: ...
    def delivery(self, delivery_id: str) -> GitHubWebhookDelivery | None: ...
    def latest_delivery(self) -> GitHubWebhookDelivery | None: ...
    def delivery_counts(self) -> dict[str, int]: ...
    def pull_request(self, repo_id: int, number: int) -> GitHubPullRequest | None: ...
    def team_prefixes(self, workspace_id: str) -> list[str]: ...
    def issues_by_keys(self, workspace_id: str, keys: set[str]) -> list[Issue]: ...
    def links(self, pull_request_id: str) -> list[IssuePullRequestLink]: ...
    def linked_pull_requests(self, issue_id: str) -> list[GitHubPullRequest]: ...
    def add(self, record: object) -> None: ...
    def reserve_delivery(self, delivery: GitHubWebhookDelivery) -> str | None: ...
    def save_changes(self) -> None: ...


class SqlAlchemyGitHubRepository:
    def __init__(self, db: Session):
        self.db = db

    def workspace_exists(self, workspace_id: str) -> bool:
        return self.db.scalar(select(Workspace.id).where(Workspace.id == workspace_id)) is not None

    def delivery(self, delivery_id: str) -> GitHubWebhookDelivery | None:
        return self.db.get(GitHubWebhookDelivery, delivery_id)

    def latest_delivery(self) -> GitHubWebhookDelivery | None:
        return self.db.scalar(
            select(GitHubWebhookDelivery).order_by(
                GitHubWebhookDelivery.received_at.desc(), GitHubWebhookDelivery.delivery_id.desc()
            ).limit(1)
        )

    def delivery_counts(self) -> dict[str, int]:
        rows = self.db.execute(
            select(GitHubWebhookDelivery.status, func.count()).group_by(GitHubWebhookDelivery.status)
        ).all()
        return {status: count for status, count in rows}

    def pull_request(self, repo_id: int, number: int) -> GitHubPullRequest | None:
        return self.db.scalar(
            select(GitHubPullRequest).where(
                GitHubPullRequest.github_repo_id == repo_id,
                GitHubPullRequest.pr_number == number,
            )
        )

    def team_prefixes(self, workspace_id: str) -> list[str]:
        return list(self.db.scalars(
            select(Team.issue_prefix).where(
                Team.workspace_id == workspace_id,
                Team.archived_at.is_(None),
            )
        ))

    def issues_by_keys(self, workspace_id: str, keys: set[str]) -> list[Issue]:
        if not keys:
            return []
        return list(self.db.scalars(
            select(Issue).where(
                Issue.workspace_id == workspace_id,
                Issue.key.in_(keys),
                Issue.archived_at.is_(None),
            )
        ))

    def links(self, pull_request_id: str) -> list[IssuePullRequestLink]:
        return list(self.db.scalars(
            select(IssuePullRequestLink).where(
                IssuePullRequestLink.pull_request_id == pull_request_id
            )
        ))

    def linked_pull_requests(self, issue_id: str) -> list[GitHubPullRequest]:
        return list(self.db.scalars(
            select(GitHubPullRequest)
            .join(IssuePullRequestLink, IssuePullRequestLink.pull_request_id == GitHubPullRequest.id)
            .where(
                IssuePullRequestLink.issue_id == issue_id,
                IssuePullRequestLink.detached_at.is_(None),
            )
            .order_by(
                GitHubPullRequest.github_updated_at.desc(),
                GitHubPullRequest.github_repo_full_name,
                GitHubPullRequest.pr_number,
            )
        ))

    def add(self, record: object) -> None:
        self.db.add(record)

    def reserve_delivery(self, delivery: GitHubWebhookDelivery) -> str | None:
        self.db.add(delivery)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.get(GitHubWebhookDelivery, delivery.delivery_id)
            return existing.status if existing is not None else "processed"
        return None

    def save_changes(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RepositoryConflictError from exc


def get_github_repository(db: DbSession) -> GitHubRepository:
    return SqlAlchemyGitHubRepository(db)


GitHubRepositoryDep = Annotated[GitHubRepository, Depends(get_github_repository)]
