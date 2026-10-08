from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: str
    file_asset_id: str
    filename: str
    team_id: str
    issue_id: str | None
    issue_key: str | None
    project_id: str | None
    project_name: str | None
    page_number: int
    heading_path: str | None
    chunk_content: str
    parent_content: str
    vector_score: float
