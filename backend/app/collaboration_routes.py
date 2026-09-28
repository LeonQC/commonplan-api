from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser
from app.issue_routes import _issue_read
from app.schemas import IssueActivityRead, IssueCollaborationRead, IssueCommentCreate, IssueCommentPatch, IssueCreate, IssueWatcherRead
from app.services.collaboration_service import CollaborationServiceDep, CollaborationValidationError
from app.services.resource_policy import ResourceForbidden, ResourceNotFound


router = APIRouter(prefix="/api/v1", tags=["collaboration"])


def _error(exc):
    if isinstance(exc, ResourceNotFound): return HTTPException(status_code=404, detail="Collaboration resource not found")
    if isinstance(exc, ResourceForbidden): return HTTPException(status_code=403, detail="Insufficient resource access")
    if isinstance(exc, CollaborationValidationError): return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/workspaces/{workspace_id}/issues/{key}/comments", response_model=IssueActivityRead, status_code=201)
def create_comment(workspace_id: str, key: str, payload: IssueCommentCreate, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return service.create_comment(current_user, workspace_id, key, payload.body, payload.mentioned_user_ids)
    except Exception as exc: raise _error(exc) from exc


@router.patch("/workspaces/{workspace_id}/issues/{key}/comments/{comment_id}", response_model=IssueActivityRead)
def update_comment(workspace_id: str, key: str, comment_id: str, payload: IssueCommentPatch, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return service.update_comment(current_user, workspace_id, key, comment_id, payload.body, payload.mentioned_user_ids)
    except Exception as exc: raise _error(exc) from exc


@router.delete("/workspaces/{workspace_id}/issues/{key}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(workspace_id: str, key: str, comment_id: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: service.delete_comment(current_user, workspace_id, key, comment_id)
    except Exception as exc: raise _error(exc) from exc


def _collaboration_read(service, current_user, workspace_id, key):
    data = service.collaboration(current_user, workspace_id, key)
    return IssueCollaborationRead(
        watching=data["watching"],
        watchers=[IssueWatcherRead(user_id=user.id, name=user.name, reason=watcher.reason, created_at=watcher.created_at) for watcher, user in data["watchers"]],
        sub_issues=[_issue_read(service.issues, issue, None) for issue in data["children"]],
    )


@router.get("/workspaces/{workspace_id}/issues/{key}/collaboration", response_model=IssueCollaborationRead)
def collaboration(workspace_id: str, key: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return _collaboration_read(service, current_user, workspace_id, key)
    except Exception as exc: raise _error(exc) from exc


@router.put("/workspaces/{workspace_id}/issues/{key}/watch", response_model=IssueCollaborationRead)
def watch(workspace_id: str, key: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try:
        service.watch(current_user, workspace_id, key)
        return _collaboration_read(service, current_user, workspace_id, key)
    except Exception as exc: raise _error(exc) from exc


@router.delete("/workspaces/{workspace_id}/issues/{key}/watch", response_model=IssueCollaborationRead)
def unwatch(workspace_id: str, key: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try:
        service.unwatch(current_user, workspace_id, key)
        return _collaboration_read(service, current_user, workspace_id, key)
    except Exception as exc: raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/issues/{key}/sub-issues", status_code=201)
def create_sub_issue(workspace_id: str, key: str, payload: IssueCreate, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return _issue_read(service.issues, *service.create_sub_issue(current_user, workspace_id, key, payload.model_dump()))
    except Exception as exc: raise _error(exc) from exc
