from typing import Annotated

from fastapi import Depends

from app.models import User
from app.operators.retrieval_operator import RetrievalOperator, RetrievalOperatorDep
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class RetrievalNotFound(Exception): pass
class RetrievalForbidden(Exception): pass
class RetrievalValidationError(Exception): pass


class RetrievalService:
    def __init__(self, operator: RetrievalOperator, workspaces: WorkspaceService) -> None:
        self.operator = operator
        self.workspaces = workspaces

    def search(self, user: User, workspace_id: str, payload: dict) -> dict:
        query = payload["query"].strip()
        if not query:
            raise RetrievalValidationError("Query cannot be blank")
        try:
            teams = self.workspaces.list_teams(user, workspace_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"):
                raise RetrievalNotFound from exc
            raise RetrievalForbidden from exc
        allowed_team_ids = [team.id for team, _membership in teams]
        team_id = payload.get("team_id")
        if team_id and team_id not in allowed_team_ids:
            raise RetrievalForbidden
        if payload.get("issue_key") and payload.get("project_id"):
            raise RetrievalValidationError("Choose either issue_key or project_id, not both")
        return self.operator.search(
            workspace_id=workspace_id,
            allowed_team_ids=allowed_team_ids,
            query=query,
            limit=payload.get("limit", 10),
            team_id=team_id,
            issue_key=payload.get("issue_key"),
            project_id=payload.get("project_id"),
        )


def get_retrieval_service(
    operator: RetrievalOperatorDep, workspaces: WorkspaceServiceDep,
) -> RetrievalService:
    return RetrievalService(operator, workspaces)


RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]
