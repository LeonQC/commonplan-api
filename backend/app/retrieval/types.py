from dataclasses import dataclass, field
from typing import Literal


RetrievalMethod = Literal["vector", "lexical"]


@dataclass(frozen=True)
class RetrievalScope:
    workspace_id: str
    team_ids: tuple[str, ...]
    project_id: str | None = None
    issue_id: str | None = None


@dataclass(frozen=True)
class SearchHit:
    node_id: str
    source_id: str
    source_type: str
    content: str
    method: RetrievalMethod
    score: float
    workspace_id: str
    team_id: str
    project_id: str | None = None
    issue_id: str | None = None
    heading_path: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def citation_target(self) -> str:
        if self.issue_id:
            return f"issue:{self.issue_id}"
        if self.project_id:
            return f"project:{self.project_id}"
        return f"{self.source_type}:{self.source_id}"
