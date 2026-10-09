from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    markdown_content: str
    plain_text: str
    heading_path: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    parser_version: str
    pages: list[ParsedPage]
    # Kept in memory only while a structure-aware chunker runs. ORM models
    # persist the normalized pages/chunks, never this parser-specific object.
    native_document: object | None = None


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    page_number: int
    content: str
    token_count: int
    heading_path: str | None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AttachmentScope:
    workspace_id: str
    team_id: str
    issue_id: str | None = None
    project_id: str | None = None
