from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import (
    DocumentChunk, DocumentIngestion, DocumentPage, FileAsset, Issue, Project,
)
from app.retrieval.types import RetrievalCandidate


class RetrievalRepository(Protocol):
    def nearest(
        self,
        *,
        workspace_id: str,
        allowed_team_ids: list[str],
        query_vector: list[float],
        embedding_provider: str,
        embedding_model: str,
        candidate_limit: int,
        team_id: str | None = None,
        issue_key: str | None = None,
        project_id: str | None = None,
    ) -> list[RetrievalCandidate]: ...


class SqlAlchemyRetrievalRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def nearest(
        self,
        *,
        workspace_id: str,
        allowed_team_ids: list[str],
        query_vector: list[float],
        embedding_provider: str,
        embedding_model: str,
        candidate_limit: int,
        team_id: str | None = None,
        issue_key: str | None = None,
        project_id: str | None = None,
    ) -> list[RetrievalCandidate]:
        if not allowed_team_ids:
            return []
        # HNSW applies relational filters after its initial approximate scan.
        # Iterative scanning preserves recall for workspace/team ACL predicates.
        self.db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        distance = DocumentChunk.embedding_vector.cosine_distance(query_vector)
        stmt = (
            select(
                DocumentChunk.id,
                DocumentIngestion.file_asset_id,
                FileAsset.original_filename,
                DocumentChunk.team_id,
                DocumentChunk.issue_id,
                Issue.key,
                DocumentChunk.project_id,
                Project.name,
                DocumentPage.page_number,
                DocumentChunk.heading_path,
                DocumentChunk.content,
                DocumentPage.plain_text,
                distance.label("distance"),
            )
            .join(DocumentIngestion, DocumentIngestion.id == DocumentChunk.ingestion_id)
            .join(DocumentPage, DocumentPage.id == DocumentChunk.parent_page_id)
            .join(FileAsset, FileAsset.id == DocumentIngestion.file_asset_id)
            .outerjoin(Issue, Issue.id == DocumentChunk.issue_id)
            .outerjoin(Project, Project.id == DocumentChunk.project_id)
            .where(
                DocumentChunk.workspace_id == workspace_id,
                DocumentChunk.team_id.in_(allowed_team_ids),
                DocumentChunk.embedding_vector.is_not(None),
                DocumentIngestion.status == "ready",
                DocumentIngestion.embedding_provider == embedding_provider,
                DocumentIngestion.embedding_model == embedding_model,
                FileAsset.deleted_at.is_(None),
            )
        )
        if team_id:
            stmt = stmt.where(DocumentChunk.team_id == team_id)
        if issue_key:
            stmt = stmt.where(Issue.key == issue_key.upper())
        if project_id:
            stmt = stmt.where(DocumentChunk.project_id == project_id)
        rows = self.db.execute(stmt.order_by(distance).limit(candidate_limit)).all()
        return [
            RetrievalCandidate(
                chunk_id=row[0],
                file_asset_id=row[1],
                filename=row[2],
                team_id=row[3],
                issue_id=row[4],
                issue_key=row[5],
                project_id=row[6],
                project_name=row[7],
                page_number=row[8],
                heading_path=row[9],
                chunk_content=row[10],
                parent_content=row[11],
                vector_score=1.0 - float(row[12]),
            )
            for row in rows
        ]


def get_retrieval_repository(db: DbSession) -> RetrievalRepository:
    return SqlAlchemyRetrievalRepository(db)


RetrievalRepositoryDep = Annotated[RetrievalRepository, Depends(get_retrieval_repository)]
