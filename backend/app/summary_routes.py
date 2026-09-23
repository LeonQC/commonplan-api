from fastapi import APIRouter, HTTPException, Query

from app.auth import CurrentUser
from app.schemas import TeamSummaryRead
from app.services.summary_service import (
    SummaryForbidden, SummaryNotFound, SummaryServiceDep, SummaryValidationError,
)


router = APIRouter(prefix="/api/v1", tags=["team summary"])


@router.get("/workspaces/{workspace_id}/teams/{team_id}/summary", response_model=TeamSummaryRead)
def team_summary(
    workspace_id: str,
    team_id: str,
    current_user: CurrentUser,
    service: SummaryServiceDep,
    cycle: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    priority: list[int] | None = Query(default=None),
    assignee: list[str] | None = Query(default=None),
    label: list[str] | None = Query(default=None),
    label_match: str = "any",
    date_from: str | None = None,
    date_to: str | None = None,
    due: str | None = None,
    include_archived: bool = False,
    ownership: str = "all",
    timezone: str = "UTC",
):
    try:
        return service.team_summary(current_user, workspace_id, team_id, {
            "cycle": cycle, "project": project, "status": status, "priority": priority,
            "assignee": assignee, "label": label, "label_match": label_match,
            "date_from": date_from, "date_to": date_to, "due": due,
            "include_archived": include_archived, "ownership": ownership, "timezone": timezone,
        })
    except SummaryNotFound as exc:
        raise HTTPException(status_code=404, detail="Summary scope not found") from exc
    except SummaryForbidden as exc:
        raise HTTPException(status_code=403, detail="Insufficient team access") from exc
    except SummaryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
