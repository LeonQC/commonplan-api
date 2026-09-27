from fastapi import APIRouter, HTTPException, Query, status

from app.auth import CurrentUser
from app.schemas import InboxRead, IssueRead, SavedViewCreate, SavedViewPatch, SavedViewRead
from app.services.view_notification_service import (
    ViewNotificationForbidden, ViewNotificationNotFound, ViewNotificationServiceDep, ViewNotificationValidationError,
)


router = APIRouter(prefix="/api/v1", tags=["views and inbox"])


def _error(exc):
    if isinstance(exc, ViewNotificationNotFound): return HTTPException(status_code=404, detail="View or notification not found")
    if isinstance(exc, ViewNotificationForbidden): return HTTPException(status_code=403, detail="Insufficient access")
    if isinstance(exc, ViewNotificationValidationError): return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/workspaces/{workspace_id}/views", response_model=list[SavedViewRead])
def list_views(workspace_id: str, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: return service.list_views(current_user, workspace_id)
    except Exception as exc: raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/views", response_model=SavedViewRead, status_code=201)
def create_view(workspace_id: str, payload: SavedViewCreate, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: return service.create_view(current_user, workspace_id, payload.model_dump())
    except Exception as exc: raise _error(exc) from exc


@router.patch("/workspaces/{workspace_id}/views/{view_id}", response_model=SavedViewRead)
def update_view(workspace_id: str, view_id: str, payload: SavedViewPatch, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: return service.update_view(current_user, workspace_id, view_id, payload.model_dump(exclude_unset=True))
    except Exception as exc: raise _error(exc) from exc


@router.delete("/workspaces/{workspace_id}/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(workspace_id: str, view_id: str, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: service.archive_view(current_user, workspace_id, view_id)
    except Exception as exc: raise _error(exc) from exc


@router.get("/workspaces/{workspace_id}/views/{view_id}/issues")
def execute_view(workspace_id: str, view_id: str, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: return service.execute_view(current_user, workspace_id, view_id)
    except Exception as exc: raise _error(exc) from exc


@router.get("/me/inbox", response_model=InboxRead)
def inbox(current_user: CurrentUser, service: ViewNotificationServiceDep, workspace_id: str | None = None, unread_only: bool = Query(False)):
    try: return service.inbox(current_user, workspace_id, unread_only)
    except Exception as exc: raise _error(exc) from exc


@router.post("/me/inbox/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notification_id: str, current_user: CurrentUser, service: ViewNotificationServiceDep):
    try: service.mark_read(current_user, notification_id)
    except Exception as exc: raise _error(exc) from exc
