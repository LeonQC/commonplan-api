from fastapi import APIRouter, HTTPException

from app.auth import CurrentUser
from app.schemas import RetrievalSearchRead, RetrievalSearchRequest
from app.services.retrieval_service import (
    RetrievalForbidden,
    RetrievalNotFound,
    RetrievalServiceDep,
    RetrievalValidationError,
)


router = APIRouter(prefix="/api/v1", tags=["retrieval"])


@router.post(
    "/workspaces/{workspace_id}/retrieval/search",
    response_model=RetrievalSearchRead,
)
def search_workspace_documents(
    workspace_id: str,
    payload: RetrievalSearchRequest,
    current_user: CurrentUser,
    service: RetrievalServiceDep,
):
    try:
        return service.search(current_user, workspace_id, payload.model_dump())
    except RetrievalNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    except RetrievalForbidden as exc:
        raise HTTPException(status_code=403, detail="Insufficient retrieval scope") from exc
    except RetrievalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
