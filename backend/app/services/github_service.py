import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends

from app.config import settings
from app.models import (
    GitHubPullRequest,
    GitHubWebhookDelivery,
    IssuePullRequestLink,
    User,
)
from app.repositories.github_repository import GitHubRepository, GitHubRepositoryDep
from app.services.issue_service import IssueService, IssueServiceDep
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class GitHubWebhookUnauthorized(Exception):
    pass


class GitHubWebhookForbidden(Exception):
    pass


class GitHubWebhookInvalid(Exception):
    pass


class GitHubIntegrationUnavailable(Exception):
    pass


class GitHubIntegrationForbidden(Exception):
    pass


class GitHubIntegrationService:
    SUPPORTED_ACTIONS = {
        "opened", "edited", "reopened", "closed", "synchronize",
        "converted_to_draft", "ready_for_review",
    }

    def __init__(
        self,
        repository: GitHubRepository,
        workspaces: WorkspaceService,
        issues: IssueService,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.issues = issues

    def accept_webhook(
        self,
        *,
        raw_body: bytes,
        payload: dict,
        signature: str | None,
        delivery_id: str | None,
        event_type: str | None,
        hook_id: str | None,
    ) -> dict:
        self._require_configuration()
        self._verify_signature(raw_body, signature)
        normalized_delivery_id = self._delivery_id(delivery_id)
        existing_delivery = self.repository.delivery(normalized_delivery_id)
        if existing_delivery is not None:
            return {"accepted": True, "duplicate": True, "status": existing_delivery.status}

        repository_payload = payload.get("repository") or {}
        owner = repository_payload.get("owner") or {}
        self._verify_source(owner, hook_id)
        now = datetime.now(timezone.utc)
        event = (event_type or "").strip()
        action = payload.get("action")
        repo_id = repository_payload.get("id")
        delivery = GitHubWebhookDelivery(
            delivery_id=normalized_delivery_id,
            github_repo_id=repo_id if isinstance(repo_id, int) else None,
            event_type=event or "unknown",
            action=action if isinstance(action, str) else None,
            status="pending",
            received_at=now,
        )
        duplicate_status = self.repository.reserve_delivery(delivery)
        if duplicate_status is not None:
            return {
                "accepted": True,
                "duplicate": True,
                "status": duplicate_status,
            }

        if event == "ping":
            delivery.status = "processed"
            delivery.processed_at = now
            self.repository.save_changes()
            return {"accepted": True, "duplicate": False, "status": "processed"}

        if event != "pull_request" or action not in self.SUPPORTED_ACTIONS:
            delivery.status = "ignored"
            delivery.error_code = "unsupported_event"
            delivery.processed_at = now
            self.repository.save_changes()
            return {"accepted": True, "duplicate": False, "status": "ignored"}

        try:
            linked_keys = self._process_pull_request(payload, now)
        except GitHubWebhookInvalid as exc:
            delivery.status = "failed"
            delivery.error_code = "invalid_payload"
            delivery.processed_at = now
            self.repository.save_changes()
            raise exc

        delivery.status = "processed"
        delivery.processed_at = now
        self.repository.save_changes()
        return {
            "accepted": True,
            "duplicate": False,
            "status": "processed",
            "linked_issue_keys": linked_keys,
        }

    def issue_pull_requests(self, user: User, workspace_id: str, issue_key: str):
        issue, _labels = self.issues.get_issue(user, workspace_id, issue_key)
        return self.repository.linked_pull_requests(issue.id)

    def health(self, user: User, workspace_id: str) -> dict:
        _workspace, membership = self.workspaces.get_workspace(user, workspace_id)
        if membership.role not in {"owner", "admin"}:
            raise GitHubIntegrationForbidden
        configured_workspace = settings.github_workspace_id
        configured = bool(
            settings.github_webhook_secret
            and settings.github_allowed_owner_id is not None
            and configured_workspace
        )
        latest = self.repository.latest_delivery() if configured_workspace == workspace_id else None
        return {
            "configured": configured and configured_workspace == workspace_id,
            "owner_login": settings.github_allowed_owner_login or None,
            "owner_id": settings.github_allowed_owner_id,
            "hook_id": settings.github_hook_id,
            "event": "pull_request",
            "webhook_path": "/webhooks/github",
            "last_delivery": latest,
            "delivery_counts": self.repository.delivery_counts() if latest else {},
        }

    def _process_pull_request(self, payload: dict, now: datetime) -> list[str]:
        repository_payload = payload.get("repository") or {}
        pull = payload.get("pull_request") or {}
        try:
            repo_id = int(repository_payload["id"])
            repo_name = str(repository_payload["full_name"])
            number = int(payload["number"])
            title = str(pull["title"])
            html_url = str(pull["html_url"])
            updated_at = self._parse_datetime(pull["updated_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubWebhookInvalid("Invalid pull_request webhook payload") from exc

        record = self.repository.pull_request(repo_id, number)
        if record is not None and self._aware(record.github_updated_at) > updated_at:
            return []

        merged_at = self._parse_datetime(pull["merged_at"]) if pull.get("merged_at") else None
        state = "merged" if merged_at or pull.get("merged") else str(pull.get("state") or "open")
        if state not in {"open", "closed", "merged"}:
            state = "closed"
        if record is None:
            record = GitHubPullRequest(
                id=str(uuid.uuid4()),
                github_repo_id=repo_id,
                github_repo_full_name=repo_name,
                pr_number=number,
                title=title,
                html_url=html_url,
                state=state,
                is_draft=bool(pull.get("draft")),
                merged_at=merged_at,
                github_updated_at=updated_at,
                last_received_at=now,
            )
            self.repository.add(record)
        else:
            record.github_repo_full_name = repo_name
            record.title = title
            record.html_url = html_url
            record.state = state
            record.is_draft = bool(pull.get("draft"))
            record.merged_at = merged_at
            record.github_updated_at = updated_at
            record.last_received_at = now

        keys = self._keys_from_title(title)
        issues = self.repository.issues_by_keys(settings.github_workspace_id, keys)
        issue_by_id = {issue.id: issue for issue in issues}
        desired_ids = set(issue_by_id)
        links = {link.issue_id: link for link in self.repository.links(record.id)}
        for issue_id, link in links.items():
            if issue_id not in desired_ids and link.detached_at is None:
                link.detached_at = now
        for issue_id in desired_ids:
            link = links.get(issue_id)
            if link is None:
                self.repository.add(IssuePullRequestLink(
                    issue_id=issue_id,
                    pull_request_id=record.id,
                    source="title_key",
                    linked_at=now,
                ))
            elif link.detached_at is not None:
                link.detached_at = None
                link.linked_at = now
        return sorted(issue.key for issue in issues)

    def _keys_from_title(self, title: str) -> set[str]:
        prefixes = self.repository.team_prefixes(settings.github_workspace_id)
        if not prefixes:
            return set()
        choices = "|".join(re.escape(prefix) for prefix in sorted(prefixes, key=len, reverse=True))
        pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{choices})-[1-9][0-9]*(?![A-Za-z0-9])")
        return set(pattern.findall(title))

    def _require_configuration(self) -> None:
        if not settings.github_webhook_secret or not settings.github_workspace_id:
            raise GitHubIntegrationUnavailable("GitHub webhook is not configured")
        if settings.github_allowed_owner_id is None:
            raise GitHubIntegrationUnavailable("GitHub owner allowlist is not configured")
        if not self.repository.workspace_exists(settings.github_workspace_id):
            raise GitHubIntegrationUnavailable("Configured GitHub workspace does not exist")

    @staticmethod
    def _verify_signature(raw_body: bytes, signature: str | None) -> None:
        expected = "sha256=" + hmac.new(
            settings.github_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise GitHubWebhookUnauthorized

    @staticmethod
    def _delivery_id(value: str | None) -> str:
        try:
            return str(uuid.UUID(value or ""))
        except (ValueError, AttributeError) as exc:
            raise GitHubWebhookInvalid("Missing or invalid X-GitHub-Delivery") from exc

    @staticmethod
    def _verify_source(owner: dict, hook_id: str | None) -> None:
        if owner.get("id") != settings.github_allowed_owner_id:
            raise GitHubWebhookForbidden
        if settings.github_hook_id is not None and str(settings.github_hook_id) != str(hook_id):
            raise GitHubWebhookForbidden

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_github_integration_service(
    repository: GitHubRepositoryDep,
    workspaces: WorkspaceServiceDep,
    issues: IssueServiceDep,
) -> GitHubIntegrationService:
    return GitHubIntegrationService(repository, workspaces, issues)


GitHubIntegrationServiceDep = Annotated[
    GitHubIntegrationService, Depends(get_github_integration_service)
]
