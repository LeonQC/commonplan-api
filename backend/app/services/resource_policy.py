from app.models import Issue, IssueComment, User
from app.services.workspace_service import WorkspaceService


class ResourceNotFound(Exception): pass
class ResourceForbidden(Exception): pass


class ResourcePolicy:
    def __init__(self, workspaces: WorkspaceService):
        self.workspaces = workspaces

    def require_issue_access(self, user: User, workspace_id: str, issue: Issue | None):
        if issue is None or issue.workspace_id != workspace_id:
            raise ResourceNotFound
        try:
            return self.workspaces.get_team(user, workspace_id, issue.team_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"):
                raise ResourceNotFound from exc
            raise ResourceForbidden from exc

    def require_comment_manager(self, user: User, workspace_id: str, issue: Issue, comment: IssueComment):
        _team, team_membership, workspace_membership = self.require_issue_access(user, workspace_id, issue)
        if comment.author_user_id == user.id:
            return
        if workspace_membership.role in {"owner", "admin"}:
            return
        if team_membership is not None and team_membership.role == "lead":
            return
        raise ResourceForbidden
