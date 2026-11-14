from typing import Annotated, Protocol

from fastapi import Depends
from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import EmbeddingProfile, KnowledgeEmbedding, KnowledgeNode, KnowledgeSource
from app.retrieval.types import RetrievalScope, SearchHit


class RetrievalRepository(Protocol):
    def vector_search(
        self,
        query_embedding: list[float],
        profile_key: str,
        scope: RetrievalScope,
        limit: int,
    ) -> list[SearchHit]: ...

    def lexical_search(
        self,
        query: str,
        scope: RetrievalScope,
        limit: int,
    ) -> list[SearchHit]: ...


class SqlAlchemyRetrievalRepository:
    """Own SQL for online retrieval, including mandatory authorization predicates."""

    def __init__(self, db: Session):
        self.db = db

    def vector_search(
        self,
        query_embedding: list[float],
        profile_key: str,
        scope: RetrievalScope,
        limit: int,
    ) -> list[SearchHit]:
        dimensions = len(query_embedding)
        vector = cast(KnowledgeEmbedding.embedding, Vector(dimensions))
        distance = vector.cosine_distance(query_embedding)
        # pgvector applies WHERE filters after an approximate HNSW scan. Iterative
        # scans continue through the profile-specific index until the requested
        # number of ACL-valid candidates is found (or the scan cap is reached).
        self.db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
        statement = (
            select(
                KnowledgeNode,
                KnowledgeSource.source_id,
                KnowledgeSource.source_type,
                (1.0 - distance).label("score"),
            )
            .join(
                KnowledgeEmbedding,
                KnowledgeEmbedding.knowledge_node_id == KnowledgeNode.id,
            )
            .join(
                EmbeddingProfile,
                EmbeddingProfile.id == KnowledgeEmbedding.embedding_profile_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeNode.knowledge_source_id,
            )
            .where(
                *self._scope_predicates(scope),
                EmbeddingProfile.profile_key == profile_key,
                KnowledgeEmbedding.embedding_profile_key
                == literal(profile_key, literal_execute=True),
                EmbeddingProfile.dimensions == dimensions,
                KnowledgeSource.active_embedding_profile_id == EmbeddingProfile.id,
                KnowledgeEmbedding.content_hash == KnowledgeNode.content_hash,
                func.vector_dims(KnowledgeEmbedding.embedding) == dimensions,
            )
            .order_by(distance, KnowledgeNode.id)
            .limit(limit)
        )
        return [
            self._hit(node, source_id, source_type, "vector", float(score))
            for node, source_id, source_type, score in self.db.execute(statement).all()
        ]

    def lexical_search(
        self,
        query: str,
        scope: RetrievalScope,
        limit: int,
    ) -> list[SearchHit]:
        document = func.to_tsvector("simple", KnowledgeNode.content)
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.greatest(
            func.ts_rank_cd(document, tsquery),
            func.similarity(KnowledgeNode.content, query),
        )
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = (
            select(
                KnowledgeNode,
                KnowledgeSource.source_id,
                KnowledgeSource.source_type,
                rank.label("score"),
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeNode.knowledge_source_id,
            )
            .where(
                *self._scope_predicates(scope),
                or_(
                    document.op("@@")(tsquery),
                    KnowledgeNode.content.ilike(f"%{escaped}%", escape="\\"),
                ),
            )
            .order_by(rank.desc(), KnowledgeNode.id)
            .limit(limit)
        )
        return [
            self._hit(node, source_id, source_type, "lexical", float(score))
            for node, source_id, source_type, score in self.db.execute(statement).all()
        ]

    @staticmethod
    def _scope_predicates(scope: RetrievalScope) -> tuple:
        predicates = [
            KnowledgeNode.workspace_id == scope.workspace_id,
            KnowledgeNode.team_id.in_(scope.team_ids),
            KnowledgeSource.workspace_id == scope.workspace_id,
            KnowledgeSource.team_id.in_(scope.team_ids),
            KnowledgeNode.indexable.is_(True),
            KnowledgeSource.status == "ready",
            KnowledgeSource.deleted_at.is_(None),
        ]
        if scope.project_id is not None:
            predicates.append(KnowledgeNode.project_id == scope.project_id)
        if scope.issue_id is not None:
            predicates.append(KnowledgeNode.issue_id == scope.issue_id)
        return tuple(predicates)

    @staticmethod
    def _hit(node, source_id, source_type, method, score) -> SearchHit:
        return SearchHit(
            node_id=node.id,
            source_id=source_id,
            source_type=source_type,
            content=node.content,
            method=method,
            score=score,
            workspace_id=node.workspace_id,
            team_id=node.team_id,
            project_id=node.project_id,
            issue_id=node.issue_id,
            heading_path=node.heading_path,
            page_from=node.page_from,
            page_to=node.page_to,
            metadata=node.node_metadata,
        )


def get_retrieval_repository(db: DbSession) -> RetrievalRepository:
    return SqlAlchemyRetrievalRepository(db)


RetrievalRepositoryDep = Annotated[RetrievalRepository, Depends(get_retrieval_repository)]
