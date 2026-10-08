from datetime import datetime, timedelta, timezone
from hashlib import sha256
import uuid

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.ingestion.chunking import count_tokens
from app.ingestion.types import AttachmentScope, ChunkDraft, ParsedDocument
from app.models import (
    DocumentChunk,
    DocumentIngestion,
    DocumentPage,
    FileAsset,
    Issue,
    IssueAttachment,
    OutboxEvent,
    Project,
    ProjectAttachment,
    Team,
)


class IngestionRepository:
    """The only ingestion component allowed to access a SQLAlchemy session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def claim_next(self, worker_id: str, lease_seconds: int) -> OutboxEvent | None:
        now = datetime.now(timezone.utc)
        expired = now - timedelta(seconds=lease_seconds)
        self.db.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.status == "processing",
                OutboxEvent.event_type.in_(("file.ready", "file.deleted")),
                or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at < expired),
            )
            .values(status="pending", locked_at=None, locked_by=None)
        )
        event = self.db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= now,
                OutboxEvent.event_type.in_(("file.ready", "file.deleted")),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            self.db.commit()
            return None
        event.status = "processing"
        event.attempts += 1
        event.locked_at = now
        event.locked_by = worker_id
        event.last_error = None
        self.db.commit()
        self.db.refresh(event)
        return event

    def file(self, file_id: str) -> FileAsset | None:
        return self.db.get(FileAsset, file_id)

    def scope(self, file_id: str) -> AttachmentScope | None:
        issue = self.db.execute(
            select(Issue.workspace_id, Issue.team_id, Issue.id)
            .join(IssueAttachment, IssueAttachment.issue_id == Issue.id)
            .where(IssueAttachment.file_asset_id == file_id)
        ).first()
        if issue:
            return AttachmentScope(issue.workspace_id, issue.team_id, issue_id=issue.id)
        project = self.db.execute(
            select(Team.workspace_id, Project.team_id, Project.id)
            .join(ProjectAttachment, ProjectAttachment.project_id == Project.id)
            .join(Team, Team.id == Project.team_id)
            .where(ProjectAttachment.file_asset_id == file_id)
        ).first()
        if project:
            return AttachmentScope(project.workspace_id, project.team_id, project_id=project.id)
        return None

    def ingestion(self, file_id: str) -> DocumentIngestion | None:
        return self.db.scalar(
            select(DocumentIngestion).where(DocumentIngestion.file_asset_id == file_id)
        )

    def is_current(
        self, file_id: str, *, content_sha256: str, chunker_version: str,
        embedding_provider: str, embedding_model: str, embedding_dimensions: int,
    ) -> bool:
        ingestion = self.ingestion(file_id)
        return bool(
            ingestion
            and ingestion.status == "ready"
            and ingestion.content_sha256 == content_sha256
            and ingestion.chunker_version == chunker_version
            and ingestion.embedding_provider == embedding_provider
            and ingestion.embedding_model == embedding_model
            and ingestion.embedding_dimensions == embedding_dimensions
        )

    def begin(
        self, file: FileAsset, *, content_sha256: str, chunker_version: str,
        embedding_provider: str, embedding_model: str, embedding_dimensions: int,
    ) -> DocumentIngestion:
        now = datetime.now(timezone.utc)
        ingestion = self.ingestion(file.id)
        if ingestion is None:
            ingestion = DocumentIngestion(
                id=str(uuid.uuid4()),
                file_asset_id=file.id,
                workspace_id=file.workspace_id,
                content_sha256=content_sha256,
                chunker_version=chunker_version,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                embedding_dimensions=embedding_dimensions,
            )
            self.db.add(ingestion)
        ingestion.status = "parsing"
        ingestion.content_sha256 = content_sha256
        ingestion.chunker_version = chunker_version
        ingestion.embedding_provider = embedding_provider
        ingestion.embedding_model = embedding_model
        ingestion.embedding_dimensions = embedding_dimensions
        ingestion.attempts = (ingestion.attempts or 0) + 1
        ingestion.error_code = None
        ingestion.error_message = None
        ingestion.started_at = now
        ingestion.completed_at = None
        ingestion.deleted_at = None
        self.db.commit()
        self.db.refresh(ingestion)
        return ingestion

    def complete_ingestion(
        self,
        ingestion_id: str,
        scope: AttachmentScope,
        document: ParsedDocument,
        chunks: list[ChunkDraft],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Embedding count does not match chunk count")
        ingestion = self.db.get(DocumentIngestion, ingestion_id)
        if ingestion is None:
            raise ValueError("Ingestion disappeared while processing")
        ingestion.status = "chunking"
        ingestion.parser_name = document.parser_name
        ingestion.parser_version = document.parser_version
        self.db.execute(delete(DocumentChunk).where(DocumentChunk.ingestion_id == ingestion_id))
        self.db.execute(delete(DocumentPage).where(DocumentPage.ingestion_id == ingestion_id))
        page_ids: dict[int, str] = {}
        for page in document.pages:
            page_id = str(uuid.uuid4())
            page_ids[page.page_number] = page_id
            self.db.add(DocumentPage(
                id=page_id,
                ingestion_id=ingestion_id,
                page_number=page.page_number,
                heading_path=page.heading_path,
                markdown_content=page.markdown_content,
                plain_text=page.plain_text,
                token_count=count_tokens(page.plain_text),
            ))
        # The models intentionally do not expose ORM relationships. Flush the
        # parent rows explicitly so PostgreSQL never sees a chunk first.
        self.db.flush()
        ingestion.status = "embedding"
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.db.add(DocumentChunk(
                id=str(uuid.uuid4()),
                ingestion_id=ingestion_id,
                parent_page_id=page_ids[chunk.page_number],
                workspace_id=scope.workspace_id,
                team_id=scope.team_id,
                issue_id=scope.issue_id,
                project_id=scope.project_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                content_hash=sha256(chunk.content.encode()).hexdigest(),
                token_count=chunk.token_count,
                page_from=chunk.page_number,
                page_to=chunk.page_number,
                heading_path=chunk.heading_path,
                embedding=embedding,
                chunk_metadata=chunk.metadata,
            ))
        ingestion.status = "ready"
        ingestion.completed_at = datetime.now(timezone.utc)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    def delete_ingestion(self, file_id: str) -> None:
        ingestion = self.ingestion(file_id)
        if ingestion is None:
            return
        self.db.execute(delete(DocumentChunk).where(DocumentChunk.ingestion_id == ingestion.id))
        self.db.execute(delete(DocumentPage).where(DocumentPage.ingestion_id == ingestion.id))
        ingestion.status = "deleted"
        ingestion.deleted_at = datetime.now(timezone.utc)
        ingestion.completed_at = datetime.now(timezone.utc)
        self.db.commit()

    def mark_ingestion_failed(self, file_id: str, code: str, message: str) -> None:
        ingestion = self.ingestion(file_id)
        if ingestion is not None:
            ingestion.status = "failed"
            ingestion.error_code = code[:80]
            ingestion.error_message = message[:4000]
            ingestion.completed_at = datetime.now(timezone.utc)
            self.db.commit()

    def publish(self, event_id: str) -> None:
        event = self.db.get(OutboxEvent, event_id)
        if event is None:
            return
        event.status = "published"
        event.published_at = datetime.now(timezone.utc)
        event.locked_at = None
        event.locked_by = None
        event.last_error = None
        self.db.commit()

    def retry_or_fail(self, event_id: str, error: str, max_attempts: int) -> None:
        event = self.db.get(OutboxEvent, event_id)
        if event is None:
            return
        event.last_error = error[:4000]
        event.locked_at = None
        event.locked_by = None
        if event.attempts >= max_attempts:
            event.status = "failed"
        else:
            event.status = "pending"
            delay = min(300, 2 ** max(0, event.attempts - 1))
            event.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self.db.commit()

    def counts(self, ingestion_id: str) -> tuple[int, int]:
        pages = len(list(self.db.scalars(
            select(DocumentPage.id).where(DocumentPage.ingestion_id == ingestion_id)
        )))
        chunks = len(list(self.db.scalars(
            select(DocumentChunk.id).where(DocumentChunk.ingestion_id == ingestion_id)
        )))
        return pages, chunks
