from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends

from app.models import User
from app.operators.summary_operator import SummaryOperator, SummaryOperatorDep
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class SummaryNotFound(Exception): pass
class SummaryForbidden(Exception): pass
class SummaryValidationError(Exception): pass


STATUS_CATEGORIES = {"backlog", "todo", "in_progress", "done", "canceled"}
DUE_STATES = {"not_due", "due_soon", "overdue", "no_due_date"}
OWNERSHIP_PRESETS = {"all", "mine", "unassigned"}


class SummaryService:
    """Authorize and normalize Summary requests before delegating read-model assembly."""

    def __init__(self, operator: SummaryOperator, workspaces: WorkspaceService):
        self.operator = operator
        self.workspaces = workspaces

    def team_summary(self, user: User, workspace_id: str, team_id: str, raw: dict):
        self._access(user, workspace_id, team_id)
        filters, timezone_info = self._normalize_filters(raw)
        try:
            return self.operator.build(user, workspace_id, team_id, filters, timezone_info)
        except ValueError as exc:
            raise SummaryValidationError(str(exc)) from exc

    @staticmethod
    def _normalize_filters(raw):
        timezone_name = raw.get("timezone") or "UTC"
        try:
            timezone_info = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise SummaryValidationError("Timezone is invalid") from exc
        categories = SummaryService._values(raw.get("status"))
        if any(value not in STATUS_CATEGORIES for value in categories):
            raise SummaryValidationError("Status filter is invalid")
        try:
            priorities = [int(value) for value in SummaryService._values(raw.get("priority"))]
        except (TypeError, ValueError) as exc:
            raise SummaryValidationError("Priority filter is invalid") from exc
        if any(value < 0 or value > 4 for value in priorities):
            raise SummaryValidationError("Priority filter is invalid")
        due = raw.get("due") or None
        if due is not None and due not in DUE_STATES:
            raise SummaryValidationError("Due-date filter is invalid")
        ownership = raw.get("ownership") or "all"
        if ownership not in OWNERSHIP_PRESETS:
            raise SummaryValidationError("Ownership filter is invalid")
        label_match = raw.get("label_match") or "any"
        if label_match not in {"any", "all"}:
            raise SummaryValidationError("Label match must be any or all")
        filters = {
            "cycle": SummaryService._values(raw.get("cycle")),
            "project": SummaryService._values(raw.get("project")),
            "status": categories,
            "priority": priorities,
            "assignee": SummaryService._values(raw.get("assignee")),
            "label": SummaryService._values(raw.get("label")),
            "label_match": label_match,
            "date_from": raw.get("date_from"),
            "date_to": raw.get("date_to"),
            "due": due,
            "include_archived": bool(raw.get("include_archived", False)),
            "ownership": ownership,
            "timezone": timezone_name,
        }
        for key in ("date_from", "date_to"):
            if filters[key]:
                try:
                    date.fromisoformat(filters[key])
                except ValueError as exc:
                    raise SummaryValidationError("Date range is invalid") from exc
        return filters, timezone_info

    @staticmethod
    def _values(value):
        return value if isinstance(value, list) else ([value] if value not in (None, "") else [])

    def _access(self, user, workspace_id, team_id):
        try:
            return self.workspaces.get_team(user, workspace_id, team_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"):
                raise SummaryNotFound from exc
            raise SummaryForbidden from exc


def get_summary_service(operator: SummaryOperatorDep, workspaces: WorkspaceServiceDep) -> SummaryService:
    return SummaryService(operator, workspaces)


SummaryServiceDep = Annotated[SummaryService, Depends(get_summary_service)]
