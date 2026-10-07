from fastapi import APIRouter, HTTPException

from app.auth import CurrentUser
from app.config import settings
from app.schemas import AttachmentDownload, AttachmentInitiate, AttachmentInitiated, AttachmentRead
from app.services.attachment_service import (
    AttachmentConflict, AttachmentForbidden, AttachmentNotFound, AttachmentServiceDep,
    AttachmentStorageError, AttachmentValidationError,
)


router = APIRouter(prefix="/api/v1", tags=["attachments"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, AttachmentNotFound):
        return HTTPException(status_code=404, detail="Attachment resource not found")
    if isinstance(exc, AttachmentForbidden):
        return HTTPException(status_code=403, detail="Insufficient team access")
    if isinstance(exc, AttachmentConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AttachmentValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, AttachmentStorageError):
        return HTTPException(status_code=503, detail=str(exc))
    raise exc


def _initiated(result: tuple) -> AttachmentInitiated:
    asset, upload_url = result
    return AttachmentInitiated(
        attachment=AttachmentRead.model_validate(asset), upload_url=upload_url,
        upload_headers={"Content-Type": asset.content_type},
    )


@router.get("/workspaces/{workspace_id}/issues/{key}/attachments", response_model=list[AttachmentRead])
def list_issue_attachments(workspace_id: str, key: str, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return service.list_issue(current_user, workspace_id, key)
    except (AttachmentNotFound, AttachmentForbidden) as exc:
        raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/issues/{key}/attachments/initiate", response_model=AttachmentInitiated, status_code=201)
def initiate_issue_attachment(workspace_id: str, key: str, payload: AttachmentInitiate, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return _initiated(service.initiate_issue(current_user, workspace_id, key, **payload.model_dump()))
    except (AttachmentNotFound, AttachmentForbidden, AttachmentConflict, AttachmentValidationError) as exc:
        raise _error(exc) from exc


@router.get("/workspaces/{workspace_id}/teams/{team_id}/projects/{project_id}/attachments", response_model=list[AttachmentRead])
def list_project_attachments(workspace_id: str, team_id: str, project_id: str, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return service.list_project(current_user, workspace_id, team_id, project_id)
    except (AttachmentNotFound, AttachmentForbidden) as exc:
        raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/teams/{team_id}/projects/{project_id}/attachments/initiate", response_model=AttachmentInitiated, status_code=201)
def initiate_project_attachment(workspace_id: str, team_id: str, project_id: str, payload: AttachmentInitiate, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return _initiated(service.initiate_project(current_user, workspace_id, team_id, project_id, **payload.model_dump()))
    except (AttachmentNotFound, AttachmentForbidden, AttachmentConflict, AttachmentValidationError) as exc:
        raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/files/{file_id}/complete", response_model=AttachmentRead)
def complete_attachment(workspace_id: str, file_id: str, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return service.complete(current_user, workspace_id, file_id)
    except (AttachmentNotFound, AttachmentForbidden, AttachmentConflict, AttachmentStorageError) as exc:
        raise _error(exc) from exc


@router.get("/workspaces/{workspace_id}/files/{file_id}/download-url", response_model=AttachmentDownload)
def attachment_download_url(workspace_id: str, file_id: str, current_user: CurrentUser, service: AttachmentServiceDep):
    try:
        return AttachmentDownload(
            download_url=service.download_url(current_user, workspace_id, file_id),
            expires_in_seconds=settings.attachment_url_ttl_seconds,
        )
    except (AttachmentNotFound, AttachmentForbidden, AttachmentConflict) as exc:
        raise _error(exc) from exc


@router.delete("/workspaces/{workspace_id}/files/{file_id}", status_code=204)
def delete_attachment(workspace_id: str, file_id: str, current_user: CurrentUser, service: AttachmentServiceDep) -> None:
    try:
        service.delete(current_user, workspace_id, file_id)
    except (AttachmentNotFound, AttachmentForbidden, AttachmentConflict, AttachmentStorageError) as exc:
        raise _error(exc) from exc
