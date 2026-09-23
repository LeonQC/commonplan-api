from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends
from sqlalchemy import select

from app.models import (
    Cycle, Issue, IssueComment, IssueEvent, IssueLabel, Label, Project, TeamMembership, User,
    WorkflowState,
)
from app.repositories.issue_repository import IssueRepository, IssueRepositoryDep
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class SummaryNotFound(Exception): pass
class SummaryForbidden(Exception): pass
class SummaryValidationError(Exception): pass


STATUS_CATEGORIES = {"backlog", "todo", "in_progress", "done", "canceled"}
DUE_STATES = {"not_due", "due_soon", "overdue", "no_due_date"}
OWNERSHIP_PRESETS = {"all", "mine", "unassigned"}
PRIORITY_LABELS = {0: "No priority", 1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}


class SummaryService:
    def __init__(self, repository: IssueRepository, workspaces: WorkspaceService):
        self.repository = repository
        self.workspaces = workspaces

    def team_summary(self, user: User, workspace_id: str, team_id: str, raw: dict):
        self._access(user, workspace_id, team_id)
        filters, timezone_info = self._normalize_filters(user, team_id, raw)
        states = {state.id: state for state in self.repository.states(team_id)}
        cycles = {cycle.id: cycle for cycle in self.repository.cycles(team_id)}
        projects = {row.id: row for row in self.repository.db.scalars(
            select(Project).where(Project.team_id == team_id, Project.archived_at.is_(None))
        )}
        members = {row.id: row for row in self.repository.db.scalars(
            select(User).join(TeamMembership, TeamMembership.user_id == User.id).where(
                TeamMembership.team_id == team_id
            )
        )}
        labels = {label.id: label for label in self.repository.labels(team_id)}
        issues = self._filtered_issues(user, team_id, filters, states, cycles, projects, members, labels)
        issue_labels = self._issue_label_map([issue.id for issue in issues])
        local_today = datetime.now(timezone.utc).astimezone(timezone_info).date()

        open_issues = [issue for issue in issues if self._category(issue, states) not in {"done", "canceled"}]
        completed = [issue for issue in issues if self._category(issue, states) == "done"]
        overdue = [issue for issue in open_issues if issue.due_date and issue.due_date < local_today]
        headline = {
            "total": len(issues),
            "open": len(open_issues),
            "in_progress": sum(self._category(issue, states) == "in_progress" for issue in issues),
            "completed": len(completed),
            "overdue": len(overdue),
            "unassigned": sum(issue.assignee_user_id is None for issue in open_issues),
        }

        status_counts = Counter(self._category(issue, states) for issue in issues)
        status_distribution = [
            {"category": category, "label": category.replace("_", " ").title(), "count": status_counts.get(category, 0)}
            for category in ("backlog", "todo", "in_progress", "done", "canceled")
        ]
        priority_counts = Counter(issue.priority for issue in issues)
        priority_distribution = [
            {"priority": priority, "label": PRIORITY_LABELS[priority], "count": priority_counts.get(priority, 0)}
            for priority in range(5)
        ]
        assignee_counts = Counter(issue.assignee_user_id for issue in open_issues)
        assignee_distribution = [
            {
                "user_id": assignee_id,
                "name": members.get(assignee_id).name if assignee_id in members else "Unassigned",
                "count": count,
            }
            for assignee_id, count in sorted(
                assignee_counts.items(), key=lambda item: (-item[1], members.get(item[0]).name if item[0] in members else "")
            )
        ]
        cycle_progress = self._cycle_progress(filters, issues, states, cycles, local_today)
        project_distribution = self._project_distribution(issues, states, projects)
        trend = self._trend(issues, states, filters, timezone_info)
        attention = {
            "overdue": [self._issue_item(issue, states, issue_labels) for issue in overdue[:5]],
            "urgent": [self._issue_item(issue, states, issue_labels) for issue in open_issues if issue.priority == 4][:5],
            "due_soon": [
                self._issue_item(issue, states, issue_labels) for issue in open_issues
                if issue.due_date and local_today <= issue.due_date <= local_today + timedelta(days=7)
            ][:5],
            "unassigned": [self._issue_item(issue, states, issue_labels) for issue in open_issues if issue.assignee_user_id is None][:5],
        }
        return {
            "scope": {"workspace_id": workspace_id, "team_id": team_id, "timezone": filters["timezone"]},
            "filters": {"version": 1, **filters},
            "headline_metrics": headline,
            "status_distribution": status_distribution,
            "priority_distribution": priority_distribution,
            "assignee_distribution": assignee_distribution,
            "cycle_progress": cycle_progress,
            "project_distribution": project_distribution,
            "trend": trend,
            "attention_issues": attention,
            "recent_activity": self._recent_activity([issue.id for issue in issues], issues),
            "matching_issues": [self._issue_item(issue, states, issue_labels) for issue in issues[:50]],
        }

    def _normalize_filters(self, user, team_id, raw):
        timezone_name = raw.get("timezone") or "UTC"
        try:
            timezone_info = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise SummaryValidationError("Timezone is invalid") from exc
        categories = self._values(raw.get("status"))
        if any(value not in STATUS_CATEGORIES for value in categories):
            raise SummaryValidationError("Status filter is invalid")
        priorities = [int(value) for value in self._values(raw.get("priority"))]
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
            "cycle": self._values(raw.get("cycle")),
            "project": self._values(raw.get("project")),
            "status": categories,
            "priority": priorities,
            "assignee": self._values(raw.get("assignee")),
            "label": self._values(raw.get("label")),
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

    def _filtered_issues(self, user, team_id, filters, states, cycles, projects, members, labels):
        stmt = select(Issue).where(Issue.team_id == team_id)
        if not filters["include_archived"]:
            stmt = stmt.where(Issue.archived_at.is_(None))
        issues = list(self.repository.db.scalars(stmt.order_by(Issue.updated_at.desc(), Issue.id)))
        self._validate_references(filters, cycles, projects, members, labels)
        selected_labels = set(filters["label"])
        issue_label_map = self._issue_label_map([issue.id for issue in issues]) if selected_labels else {}
        today = date.today()

        def matches(issue):
            if filters["cycle"] and not self._nullable_match(issue.cycle_id, filters["cycle"]): return False
            if filters["project"] and not self._nullable_match(issue.project_id, filters["project"]): return False
            if filters["status"] and self._category(issue, states) not in filters["status"]: return False
            if filters["priority"] and issue.priority not in filters["priority"]: return False
            if filters["assignee"] and not self._nullable_match(str(issue.assignee_user_id) if issue.assignee_user_id else None, filters["assignee"], "unassigned"): return False
            if filters["ownership"] == "mine" and issue.assignee_user_id != user.id: return False
            if filters["ownership"] == "unassigned" and issue.assignee_user_id is not None: return False
            if selected_labels:
                assigned = set(issue_label_map.get(issue.id, []))
                if filters["label_match"] == "all" and not selected_labels.issubset(assigned): return False
                if filters["label_match"] == "any" and not selected_labels.intersection(assigned): return False
            if filters["due"] == "no_due_date" and issue.due_date is not None: return False
            if filters["due"] == "overdue" and not (issue.due_date and issue.due_date < today and self._category(issue, states) not in {"done", "canceled"}): return False
            if filters["due"] == "due_soon" and not (issue.due_date and issue.workflow_state.type not in {"done", "canceled"} and today <= issue.due_date <= today + timedelta(days=7)): return False
            if filters["due"] == "not_due" and not (issue.due_date and issue.workflow_state.type not in {"done", "canceled"} and issue.due_date > today + timedelta(days=7)): return False
            return True

        return [issue for issue in issues if matches(issue)]

    def _validate_references(self, filters, cycles, projects, members, labels):
        for value in filters["cycle"]:
            if value != "none" and value not in cycles: raise SummaryValidationError("Cycle filter must belong to the selected team")
        for value in filters["project"]:
            if value != "none" and value not in projects: raise SummaryValidationError("Project filter must belong to the selected team")
        for value in filters["assignee"]:
            if value != "unassigned" and (not value.isdigit() or int(value) not in members): raise SummaryValidationError("Assignee filter must belong to the selected team")
        for value in filters["label"]:
            if value not in labels: raise SummaryValidationError("Label filter must belong to the selected team")

    def _issue_label_map(self, issue_ids):
        if not issue_ids: return {}
        rows = self.repository.db.execute(
            select(IssueLabel.issue_id, IssueLabel.label_id).where(IssueLabel.issue_id.in_(issue_ids))
        )
        result = defaultdict(list)
        for issue_id, label_id in rows: result[issue_id].append(label_id)
        return result

    def _cycle_progress(self, filters, issues, states, cycles, today):
        explicit = [value for value in filters["cycle"] if value != "none"]
        cycle = cycles.get(explicit[0]) if len(explicit) == 1 else next(
            (row for row in cycles.values() if row.starts_on <= today < row.ends_on), None
        )
        if cycle is None: return None
        rows = [issue for issue in issues if issue.cycle_id == cycle.id and self._category(issue, states) != "canceled"]
        completed = sum(self._category(issue, states) == "done" for issue in rows)
        return {"id": cycle.id, "name": cycle.name, "completed": completed, "total": len(rows), "percent": round(completed * 100 / len(rows)) if rows else 0}

    def _project_distribution(self, issues, states, projects):
        grouped = defaultdict(list)
        for issue in issues: grouped[issue.project_id].append(issue)
        rows = []
        for project_id, project_issues in grouped.items():
            relevant = [issue for issue in project_issues if self._category(issue, states) != "canceled"]
            completed = sum(self._category(issue, states) == "done" for issue in relevant)
            rows.append({
                "project_id": project_id,
                "name": projects[project_id].name if project_id in projects else "No project",
                "count": len(project_issues), "completed": completed,
                "total": len(relevant), "percent": round(completed * 100 / len(relevant)) if relevant else 0,
            })
        return sorted(rows, key=lambda row: (-row["count"], row["name"]))

    def _trend(self, issues, states, filters, timezone_info):
        today = datetime.now(timezone.utc).astimezone(timezone_info).date()
        start = date.fromisoformat(filters["date_from"]) if filters["date_from"] else today - timedelta(days=13)
        end = date.fromisoformat(filters["date_to"]) if filters["date_to"] else today
        if start > end or (end - start).days > 366: raise SummaryValidationError("Date range is invalid")
        created = Counter(issue.created_at.astimezone(timezone_info).date() for issue in issues)
        issue_ids = [issue.id for issue in issues]
        completed = Counter()
        if issue_ids:
            events = self.repository.db.scalars(select(IssueEvent).where(
                IssueEvent.issue_id.in_(issue_ids), IssueEvent.event_type == "issue.updated"
            ))
            done_state_ids = {state.id for state in states.values() if state.category == "done"}
            for event in events:
                target = event.changes.get("fields", {}).get("workflow_state_id", {}).get("to")
                if target in done_state_ids: completed[event.created_at.astimezone(timezone_info).date()] += 1
        buckets = []
        current = start
        while current <= end:
            buckets.append({"date": current.isoformat(), "created": created[current], "completed": completed[current]})
            current += timedelta(days=1)
        return {"from": start.isoformat(), "to": end.isoformat(), "buckets": buckets}

    def _recent_activity(self, issue_ids, issues):
        if not issue_ids: return []
        issue_map = {issue.id: issue for issue in issues}
        rows = []
        for event in self.repository.db.scalars(select(IssueEvent).where(IssueEvent.issue_id.in_(issue_ids)).order_by(IssueEvent.created_at.desc()).limit(12)):
            issue = issue_map[event.issue_id]
            actor = self.repository.user(event.actor_user_id)
            rows.append({"id": event.id, "kind": "event", "issue_key": issue.key, "issue_title": issue.title, "actor_name": actor.name if actor else None, "event_type": event.event_type, "created_at": event.created_at})
        for comment in self.repository.db.scalars(select(IssueComment).where(IssueComment.issue_id.in_(issue_ids), IssueComment.deleted_at.is_(None)).order_by(IssueComment.created_at.desc()).limit(12)):
            issue = issue_map[comment.issue_id]
            actor = self.repository.user(comment.author_user_id)
            rows.append({"id": comment.id, "kind": "comment", "issue_key": issue.key, "issue_title": issue.title, "actor_name": actor.name if actor else None, "event_type": "comment.created", "created_at": comment.created_at})
        return sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)[:12]

    def _issue_item(self, issue, states, issue_labels):
        return {"id": issue.id, "key": issue.key, "title": issue.title, "status": states[issue.workflow_state_id].name, "status_category": self._category(issue, states), "priority": issue.priority, "assignee_user_id": issue.assignee_user_id, "project_id": issue.project_id, "cycle_id": issue.cycle_id, "due_date": issue.due_date, "label_ids": issue_labels.get(issue.id, [])}

    @staticmethod
    def _category(issue, states): return states[issue.workflow_state_id].category
    @staticmethod
    def _values(value): return value if isinstance(value, list) else ([value] if value not in (None, "") else [])
    @staticmethod
    def _nullable_match(actual, selected, empty="none"): return (actual in selected) or (actual is None and empty in selected)

    def _access(self, user, workspace_id, team_id):
        try: return self.workspaces.get_team(user, workspace_id, team_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"): raise SummaryNotFound from exc
            raise SummaryForbidden from exc


def get_summary_service(repository: IssueRepositoryDep, workspaces: WorkspaceServiceDep) -> SummaryService:
    return SummaryService(repository, workspaces)


SummaryServiceDep = Annotated[SummaryService, Depends(get_summary_service)]
