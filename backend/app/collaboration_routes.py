from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser
from app.issue_routes import _issue_read
from app.schemas import (
    IssueActivityRead, IssueCollaborationRead, IssueCommentCreate, IssueCommentPatch,
    IssueCreate, IssueRelationCreate, IssueRelationRead, IssueRelationSummaryRead, IssueRelationTypeCreate,
    IssueRelationTypeRead, IssueWatcherRead,
)
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


def _relation_read(service, row):
    relation = row["relation"]
    relation_type = row["type"]
    return IssueRelationRead(
        id=relation.id,
        relation_type_id=relation.relation_type_id,
        type_key=relation_type.key,
        direction=row["direction"],
        label=row["label"],
        related_issue=_issue_read(service.issues, row["related"], None),
        created_by_user_id=relation.created_by_user_id,
        created_at=relation.created_at,
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


@router.get("/workspaces/{workspace_id}/relation-types", response_model=list[IssueRelationTypeRead])
def relation_types(workspace_id: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return service.relation_types(current_user, workspace_id)
    except Exception as exc: raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/relation-types", response_model=IssueRelationTypeRead, status_code=201)
def create_relation_type(workspace_id: str, payload: IssueRelationTypeCreate, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return service.create_relation_type(current_user, workspace_id, payload.model_dump())
    except Exception as exc: raise _error(exc) from exc


@router.get("/workspaces/{workspace_id}/issues/{key}/relations", response_model=list[IssueRelationRead])
def issue_relations(workspace_id: str, key: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return [_relation_read(service, row) for row in service.relations(current_user, workspace_id, key)]
    except Exception as exc: raise _error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/teams/{team_id}/issue-relation-summaries",
    response_model=list[IssueRelationSummaryRead],
)
def issue_relation_summaries(workspace_id: str, team_id: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: return service.relation_summaries(current_user, workspace_id, team_id)
    except Exception as exc: raise _error(exc) from exc


@router.post("/workspaces/{workspace_id}/issues/{key}/relations", response_model=IssueRelationRead, status_code=201)
def create_issue_relation(workspace_id: str, key: str, payload: IssueRelationCreate, current_user: CurrentUser, service: CollaborationServiceDep):
    try:
        row = service.create_relation(
            current_user, workspace_id, key,
            payload.relation_type_id, payload.target_issue_key, payload.direction,
        )
        return _relation_read(service, row)
    except Exception as exc: raise _error(exc) from exc


@router.delete("/workspaces/{workspace_id}/issues/{key}/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_issue_relation(workspace_id: str, key: str, relation_id: str, current_user: CurrentUser, service: CollaborationServiceDep):
    try: service.delete_relation(current_user, workspace_id, key, relation_id)
    except Exception as exc: raise _error(exc) from exc
