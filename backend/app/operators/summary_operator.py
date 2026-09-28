from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends

from app.models import User
from app.repositories.issue_repository import IssueRepository, IssueRepositoryDep
from app.repositories.project_repository import ProjectRepository, ProjectRepositoryDep
from app.repositories.workspace_repository import WorkspaceRepository, WorkspaceRepositoryDep


PRIORITY_LABELS = {0: "No priority", 1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}


class SummaryOperator:
    """Build the cross-domain Summary read model without owning a database session."""

    def __init__(
        self,
        issues: IssueRepository,
        projects: ProjectRepository,
        workspaces: WorkspaceRepository,
    ):
        self.issues = issues
        self.projects = projects
        self.workspaces = workspaces

    def build(self, user: User, workspace_id: str, team_id: str, filters: dict, timezone_info: ZoneInfo):
        states = {state.id: state for state in self.issues.states(team_id)}
        cycles = {cycle.id: cycle for cycle in self.issues.cycles(team_id)}
        projects = {project.id: project for project in self.projects.projects(team_id)}
        members = {member.id: member for member, _membership in self.workspaces.team_members(team_id)}
        labels = {label.id: label for label in self.issues.labels(team_id)}
        matching_issues = self._filtered_issues(user, team_id, filters, states, cycles, projects, members, labels)
        issue_labels = self._issue_label_map([issue.id for issue in matching_issues])
        local_today = datetime.now(timezone.utc).astimezone(timezone_info).date()

        open_issues = [issue for issue in matching_issues if self._category(issue, states) not in {"done", "canceled"}]
        completed = [issue for issue in matching_issues if self._category(issue, states) == "done"]
        overdue = [issue for issue in open_issues if issue.due_date and issue.due_date < local_today]
        headline = {
            "total": len(matching_issues),
            "open": len(open_issues),
            "in_progress": sum(self._category(issue, states) == "in_progress" for issue in matching_issues),
            "completed": len(completed),
            "overdue": len(overdue),
            "unassigned": sum(issue.assignee_user_id is None for issue in open_issues),
        }

        status_counts = Counter(self._category(issue, states) for issue in matching_issues)
        status_distribution = [
            {"category": category, "label": category.replace("_", " ").title(), "count": status_counts.get(category, 0)}
            for category in ("backlog", "todo", "in_progress", "done", "canceled")
        ]
        priority_counts = Counter(issue.priority for issue in matching_issues)
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
                assignee_counts.items(),
                key=lambda item: (-item[1], members.get(item[0]).name if item[0] in members else ""),
            )
        ]
        return {
            "scope": {"workspace_id": workspace_id, "team_id": team_id, "timezone": filters["timezone"]},
            "filters": {"version": 1, **filters},
            "headline_metrics": headline,
            "status_distribution": status_distribution,
            "priority_distribution": priority_distribution,
            "assignee_distribution": assignee_distribution,
            "cycle_progress": self._cycle_progress(filters, matching_issues, states, cycles, local_today),
            "project_distribution": self._project_distribution(matching_issues, states, projects),
            "trend": self._trend(matching_issues, states, filters, timezone_info),
            "attention_issues": {
                "overdue": [self._issue_item(issue, states, issue_labels) for issue in overdue[:5]],
                "urgent": [self._issue_item(issue, states, issue_labels) for issue in open_issues if issue.priority == 4][:5],
                "due_soon": [
                    self._issue_item(issue, states, issue_labels)
                    for issue in open_issues
                    if issue.due_date and local_today <= issue.due_date <= local_today + timedelta(days=7)
                ][:5],
                "unassigned": [
                    self._issue_item(issue, states, issue_labels)
                    for issue in open_issues
                    if issue.assignee_user_id is None
                ][:5],
            },
            "recent_activity": self._recent_activity([issue.id for issue in matching_issues], matching_issues),
            "matching_issues": [
                self._issue_item(issue, states, issue_labels) for issue in matching_issues[:50]
            ],
        }

    def _filtered_issues(self, user, team_id, filters, states, cycles, projects, members, labels):
        issues = self.issues.recently_updated_issues(
            team_id,
            include_archived=filters["include_archived"],
        )
        self._validate_references(filters, cycles, projects, members, labels)
        selected_labels = set(filters["label"])
        issue_label_map = self._issue_label_map([issue.id for issue in issues]) if selected_labels else {}
        today = date.today()

        def matches(issue):
            category = self._category(issue, states)
            if filters["cycle"] and not self._nullable_match(issue.cycle_id, filters["cycle"]): return False
            if filters["project"] and not self._nullable_match(issue.project_id, filters["project"]): return False
            if filters["status"] and category not in filters["status"]: return False
            if filters["priority"] and issue.priority not in filters["priority"]: return False
            if filters["assignee"] and not self._nullable_match(str(issue.assignee_user_id) if issue.assignee_user_id else None, filters["assignee"], "unassigned"): return False
            if filters["ownership"] == "mine" and issue.assignee_user_id != user.id: return False
            if filters["ownership"] == "unassigned" and issue.assignee_user_id is not None: return False
            if selected_labels:
                assigned = set(issue_label_map.get(issue.id, []))
                if filters["label_match"] == "all" and not selected_labels.issubset(assigned): return False
                if filters["label_match"] == "any" and not selected_labels.intersection(assigned): return False
            if filters["due"] == "no_due_date" and issue.due_date is not None: return False
            if filters["due"] == "overdue" and not (issue.due_date and issue.due_date < today and category not in {"done", "canceled"}): return False
            if filters["due"] == "due_soon" and not (issue.due_date and category not in {"done", "canceled"} and today <= issue.due_date <= today + timedelta(days=7)): return False
            if filters["due"] == "not_due" and not (issue.due_date and category not in {"done", "canceled"} and issue.due_date > today + timedelta(days=7)): return False
            return True

        return [issue for issue in issues if matches(issue)]

    @staticmethod
    def _validate_references(filters, cycles, projects, members, labels):
        for value in filters["cycle"]:
            if value != "none" and value not in cycles: raise ValueError("Cycle filter must belong to the selected team")
        for value in filters["project"]:
            if value != "none" and value not in projects: raise ValueError("Project filter must belong to the selected team")
        for value in filters["assignee"]:
            if value != "unassigned" and (not value.isdigit() or int(value) not in members): raise ValueError("Assignee filter must belong to the selected team")
        for value in filters["label"]:
            if value not in labels: raise ValueError("Label filter must belong to the selected team")

    def _issue_label_map(self, issue_ids):
        result = defaultdict(list)
        for issue_id, label_id in self.issues.issue_label_pairs(issue_ids):
            result[issue_id].append(label_id)
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

    @staticmethod
    def _project_distribution(issues, states, projects):
        grouped = defaultdict(list)
        for issue in issues:
            grouped[issue.project_id].append(issue)
        rows = []
        for project_id, project_issues in grouped.items():
            relevant = [issue for issue in project_issues if states[issue.workflow_state_id].category != "canceled"]
            completed = sum(states[issue.workflow_state_id].category == "done" for issue in relevant)
            rows.append({
                "project_id": project_id,
                "name": projects[project_id].name if project_id in projects else "No project",
                "count": len(project_issues),
                "completed": completed,
                "total": len(relevant),
                "percent": round(completed * 100 / len(relevant)) if relevant else 0,
            })
        return sorted(rows, key=lambda row: (-row["count"], row["name"]))

    def _trend(self, issues, states, filters, timezone_info):
        today = datetime.now(timezone.utc).astimezone(timezone_info).date()
        start = date.fromisoformat(filters["date_from"]) if filters["date_from"] else today - timedelta(days=13)
        end = date.fromisoformat(filters["date_to"]) if filters["date_to"] else today
        if start > end or (end - start).days > 366:
            raise ValueError("Date range is invalid")
        created = Counter(issue.created_at.astimezone(timezone_info).date() for issue in issues)
        completed = Counter()
        done_state_ids = {state.id for state in states.values() if state.category == "done"}
        for event in self.issues.events_for_issues([issue.id for issue in issues], event_type="issue.updated"):
            target = event.changes.get("fields", {}).get("workflow_state_id", {}).get("to")
            if target in done_state_ids:
                completed[event.created_at.astimezone(timezone_info).date()] += 1
        buckets = []
        current = start
        while current <= end:
            buckets.append({"date": current.isoformat(), "created": created[current], "completed": completed[current]})
            current += timedelta(days=1)
        return {"from": start.isoformat(), "to": end.isoformat(), "buckets": buckets}

    def _recent_activity(self, issue_ids, issues):
        if not issue_ids:
            return []
        issue_map = {issue.id: issue for issue in issues}
        events = self.issues.events_for_issues(issue_ids, limit=12)
        comments = self.issues.comments_for_issues(issue_ids, limit=12)
        actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
        actor_ids.update(comment.author_user_id for comment in comments)
        actors = {user.id: user for user in self.issues.users(actor_ids)}
        rows = [
            {
                "id": event.id,
                "kind": "event",
                "issue_key": issue_map[event.issue_id].key,
                "issue_title": issue_map[event.issue_id].title,
                "actor_name": actors.get(event.actor_user_id).name if event.actor_user_id in actors else None,
                "event_type": event.event_type,
                "created_at": event.created_at,
            }
            for event in events
        ]
        rows.extend({
            "id": comment.id,
            "kind": "comment",
            "issue_key": issue_map[comment.issue_id].key,
            "issue_title": issue_map[comment.issue_id].title,
            "actor_name": actors.get(comment.author_user_id).name if comment.author_user_id in actors else None,
            "event_type": "comment.created",
            "created_at": comment.created_at,
        } for comment in comments)
        return sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)[:12]

    @staticmethod
    def _issue_item(issue, states, issue_labels):
        return {"id": issue.id, "key": issue.key, "title": issue.title, "status": states[issue.workflow_state_id].name, "status_category": states[issue.workflow_state_id].category, "priority": issue.priority, "assignee_user_id": issue.assignee_user_id, "project_id": issue.project_id, "cycle_id": issue.cycle_id, "due_date": issue.due_date, "label_ids": issue_labels.get(issue.id, [])}

    @staticmethod
    def _category(issue, states): return states[issue.workflow_state_id].category
    @staticmethod
    def _nullable_match(actual, selected, empty="none"): return (actual in selected) or (actual is None and empty in selected)


def get_summary_operator(
    issues: IssueRepositoryDep,
    projects: ProjectRepositoryDep,
    workspaces: WorkspaceRepositoryDep,
) -> SummaryOperator:
    return SummaryOperator(issues, projects, workspaces)


SummaryOperatorDep = Annotated[SummaryOperator, Depends(get_summary_operator)]
