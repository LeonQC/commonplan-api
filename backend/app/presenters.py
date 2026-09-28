from app.models import Issue, Label, WorkflowState
from app.schemas import IssueRead, LabelRead


def issue_read(issue: Issue, state: WorkflowState, labels: list[Label]) -> IssueRead:
    """Convert an issue snapshot to its API shape without reaching into persistence."""
    return IssueRead(
        id=issue.id,
        workspace_id=issue.workspace_id,
        team_id=issue.team_id,
        number=issue.number,
        key=issue.key,
        title=issue.title,
        description=issue.description,
        workflow_state_id=issue.workflow_state_id,
        workflow_state_name=state.name,
        workflow_category=state.category,
        priority=issue.priority,
        creator_user_id=issue.creator_user_id,
        assignee_user_id=issue.assignee_user_id,
        cycle_id=issue.cycle_id,
        due_date=issue.due_date,
        version=issue.version,
        project_id=issue.project_id,
        milestone_id=issue.milestone_id,
        parent_issue_id=issue.parent_issue_id,
        labels=[LabelRead.model_validate(label) for label in labels],
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )
