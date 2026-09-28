import json

from fastapi import APIRouter, HTTPException, Request, status

from app.auth import CurrentUser
from app.schemas import GitHubIntegrationHealthRead, GitHubPullRequestRead
from app.services.github_service import (
    GitHubIntegrationForbidden,
    GitHubIntegrationServiceDep,
    GitHubIntegrationUnavailable,
    GitHubWebhookForbidden,
    GitHubWebhookInvalid,
    GitHubWebhookUnauthorized,
)
from app.services.issue_service import IssueForbidden, IssueNotFound


webhook_router = APIRouter(tags=["GitHub webhook"])
router = APIRouter(prefix="/api/v1", tags=["GitHub integration"])


@webhook_router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def receive_github_webhook(
    request: Request,
    service: GitHubIntegrationServiceDep,
) -> dict:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    try:
        return service.accept_webhook(
            raw_body=raw_body,
            payload=payload,
            signature=request.headers.get("X-Hub-Signature-256"),
            delivery_id=request.headers.get("X-GitHub-Delivery"),
            event_type=request.headers.get("X-GitHub-Event"),
            hook_id=request.headers.get("X-GitHub-Hook-ID"),
        )
    except GitHubWebhookUnauthorized as exc:
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature") from exc
    except GitHubWebhookForbidden as exc:
        raise HTTPException(status_code=403, detail="GitHub webhook source is not allowed") from exc
    except GitHubWebhookInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/workspaces/{workspace_id}/integrations/github",
    response_model=GitHubIntegrationHealthRead,
)
def github_integration_health(
    workspace_id: str,
    current_user: CurrentUser,
    service: GitHubIntegrationServiceDep,
) -> dict:
    try:
        return service.health(current_user, workspace_id)
    except GitHubIntegrationForbidden as exc:
        raise HTTPException(status_code=403, detail="Workspace admin access required") from exc


@router.get(
    "/workspaces/{workspace_id}/issues/{issue_key}/pull-requests",
    response_model=list[GitHubPullRequestRead],
)
def issue_pull_requests(
    workspace_id: str,
    issue_key: str,
    current_user: CurrentUser,
    service: GitHubIntegrationServiceDep,
):
    try:
        return service.issue_pull_requests(current_user, workspace_id, issue_key)
    except IssueNotFound as exc:
        raise HTTPException(status_code=404, detail="Issue not found") from exc
    except IssueForbidden as exc:
        raise HTTPException(status_code=403, detail="Insufficient team access") from exc
