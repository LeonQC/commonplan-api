from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.config import settings
from app.infrastructure.object_storage import LocalObjectStorage, StoredObject
from app.ingestion.embeddings import LocalHashEmbeddingProvider
from app.ingestion.parsers import ParserRegistry
from app.ingestion.service import IngestionService
from app.models import DocumentChunk, DocumentIngestion, DocumentPage, OutboxEvent, User
from app.repositories.attachment_repository import SqlAlchemyAttachmentRepository
from app.repositories.issue_repository import SqlAlchemyIssueRepository
from app.repositories.ingestion_repository import IngestionRepository
from app.repositories.project_repository import SqlAlchemyProjectRepository
from app.repositories.workspace_repository import SqlAlchemyWorkspaceRepository
from app.services.attachment_service import (
    AttachmentConflict, AttachmentForbidden, AttachmentService, AttachmentValidationError,
)
from app.services.issue_service import IssueService
from app.services.project_service import ProjectService
from app.services.workspace_service import WorkspaceService


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.content = {}
        self.deleted = []

    def upload_url(self, storage_key, content_type, byte_size):
        return f"https://uploads.example/{storage_key}?type={content_type}"

    def download_url(self, storage_key, filename):
        return f"https://downloads.example/{storage_key}?filename={filename}"

    def stat(self, storage_key):
        return self.objects.get(storage_key)

    def read(self, storage_key):
        return self.content[storage_key]

    def delete(self, storage_key):
        self.deleted.append(storage_key)
        self.objects.pop(storage_key, None)
        self.content.pop(storage_key, None)


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(timezone.utc)
        owner = User(
            email="owner@example.com", name="Owner", auth_issuer="issuer",
            auth_subject="owner", is_deleted=False, created_at=now, updated_at=now,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        workspaces = WorkspaceService(SqlAlchemyWorkspaceRepository(db))
        workspace, _ = workspaces.create_workspace(owner, name="CommonPlan", slug="commonplan", description=None)
        team, _ = workspaces.create_team(owner, workspace.id, name="Core", issue_prefix="KEY", description=None)
        issue = IssueService(SqlAlchemyIssueRepository(db), workspaces).create_issue(
            owner, workspace.id, team.id, title="Attach a design", label_ids=[]
        )[0]
        project = ProjectService(SqlAlchemyProjectRepository(db), workspaces).create_project(
            owner, workspace.id, team.id, name="Attachment project", status="planned"
        )["project"]
        storage = FakeStorage()
        service = AttachmentService(SqlAlchemyAttachmentRepository(db), workspaces, storage)
        yield db, service, storage, owner, workspace, team, issue, project


def test_issue_attachment_upload_complete_download_delete_and_outbox(context):
    db, service, storage, owner, workspace, _team, issue, _project = context
    asset, upload_url = service.initiate_issue(
        owner, workspace.id, issue.key, filename="architecture.pdf",
        content_type="application/pdf", byte_size=2048, sha256="a" * 64,
    )
    assert upload_url.startswith("https://uploads.example/")
    assert service.list_issue(owner, workspace.id, issue.key)[0].upload_status == "pending"

    with pytest.raises(AttachmentConflict):
        service.complete(owner, workspace.id, asset.id)

    storage.objects[asset.storage_key] = StoredObject(2048, "application/pdf")
    completed = service.complete(owner, workspace.id, asset.id)
    assert completed.upload_status == "ready"
    assert service.complete(owner, workspace.id, asset.id).id == completed.id
    assert "architecture.pdf" in service.download_url(owner, workspace.id, asset.id)
    assert len(list(db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "file.ready")))) == 1

    service.delete(owner, workspace.id, asset.id)
    assert service.list_issue(owner, workspace.id, issue.key) == []
    assert asset.storage_key in storage.deleted
    assert db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "file.deleted")).one()


def test_project_attachment_and_validation(context):
    _db, service, storage, owner, workspace, team, _issue, project = context
    asset, _ = service.initiate_project(
        owner, workspace.id, team.id, project.id, filename="brief.md",
        content_type="text/markdown", byte_size=12, sha256=None,
    )
    storage.objects[asset.storage_key] = StoredObject(12, "text/markdown")
    service.complete(owner, workspace.id, asset.id)
    assert service.list_project(owner, workspace.id, team.id, project.id)[0].id == asset.id

    with pytest.raises(AttachmentValidationError):
        service.initiate_project(
            owner, workspace.id, team.id, project.id, filename="../../secret",
            content_type="text/plain", byte_size=10, sha256=None,
        )


def test_attachment_access_fails_for_non_member(context):
    db, service, _storage, _owner, workspace, team, issue, project = context
    outsider = User(
        email="outsider@example.com", name="Outsider", auth_issuer="issuer",
        auth_subject="outsider", is_deleted=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    db.add(outsider)
    db.commit()
    db.refresh(outsider)

    with pytest.raises(AttachmentForbidden):
        service.list_issue(outsider, workspace.id, issue.key)
    with pytest.raises(AttachmentForbidden):
        service.list_project(outsider, workspace.id, team.id, project.id)


def test_local_storage_urls_are_signed_and_bytes_stay_outside_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_storage_local_path", str(tmp_path))
    monkeypatch.setattr(settings, "object_storage_local_public_url", "http://api.test")
    storage = LocalObjectStorage()
    key = "workspaces/workspace-1/file-1"
    upload_url = storage.upload_url(key, "text/plain", 5)
    assert upload_url.startswith("http://api.test/storage/uploads/")
    assert "signature=" in upload_url

    storage.put(key, b"hello")
    assert storage.stat(key) == StoredObject(byte_size=5, content_type=None)
    assert storage.path(key).read_bytes() == b"hello"
    assert "signature=" in storage.download_url(key, "hello.txt")


def test_ready_event_is_ingested_idempotently_and_delete_tombstones(context, monkeypatch):
    db, attachments, storage, owner, workspace, _team, issue, _project = context
    content = ("# Retrieval notes\n" + " ".join(f"word-{i}" for i in range(24))).encode()
    asset, _ = attachments.initiate_issue(
        owner, workspace.id, issue.key, filename="notes.md",
        content_type="text/markdown", byte_size=len(content), sha256=None,
    )
    storage.objects[asset.storage_key] = StoredObject(len(content), "text/markdown")
    storage.content[asset.storage_key] = content
    attachments.complete(owner, workspace.id, asset.id)
    monkeypatch.setattr(settings, "ingestion_chunk_tokens", 10)
    monkeypatch.setattr(settings, "ingestion_chunk_overlap_tokens", 2)

    repository = IngestionRepository(db)
    event = repository.claim_next("test-worker", lease_seconds=60)
    assert event is not None and event.status == "processing"
    ingestion = IngestionService(
        repository, storage, ParserRegistry(), LocalHashEmbeddingProvider(16)
    )
    ingestion.process(event)

    record = db.scalars(select(DocumentIngestion)).one()
    assert record.status == "ready"
    assert record.embedding_provider == "local_hash"
    assert len(list(db.scalars(select(DocumentPage)))) == 1
    chunks = list(db.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
    assert len(chunks) == 4
    assert len(chunks[0].embedding) == 16
    assert chunks[0].issue_id == issue.id and chunks[0].project_id is None
    assert db.get(OutboxEvent, event.id).status == "published"
    assert attachments.ingestion_status(owner, workspace.id, asset.id)["chunk_count"] == 4

    duplicate = OutboxEvent(
        id="duplicate-ready", workspace_id=workspace.id, aggregate_type="file_asset",
        aggregate_id=asset.id, event_type="file.ready", payload={"file_id": asset.id},
    )
    db.add(duplicate)
    db.commit()
    duplicate = repository.claim_next("test-worker", lease_seconds=60)
    ingestion.process(duplicate)
    assert len(list(db.scalars(select(DocumentChunk)))) == 4

    attachments.delete(owner, workspace.id, asset.id)
    deleted = repository.claim_next("test-worker", lease_seconds=60)
    assert deleted is not None and deleted.event_type == "file.deleted"
    ingestion.process(deleted)
    db.refresh(record)
    assert record.status == "deleted"
    assert list(db.scalars(select(DocumentPage))) == []
    assert list(db.scalars(select(DocumentChunk))) == []


def test_outbox_failure_retries_then_moves_to_failed(context):
    db, _attachments, _storage, _owner, workspace, _team, _issue, _project = context
    event = OutboxEvent(
        id="retry-event", workspace_id=workspace.id, aggregate_type="file_asset",
        aggregate_id="missing-file", event_type="file.ready",
        payload={"file_id": "missing-file"},
    )
    db.add(event)
    db.commit()
    repository = IngestionRepository(db)

    claimed = repository.claim_next("worker-a", lease_seconds=60)
    assert claimed.id == event.id and claimed.attempts == 1
    repository.retry_or_fail(event.id, "temporary failure", max_attempts=2)
    db.refresh(event)
    assert event.status == "pending" and event.last_error == "temporary failure"

    event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    claimed = repository.claim_next("worker-b", lease_seconds=60)
    assert claimed.id == event.id and claimed.attempts == 2
    repository.retry_or_fail(event.id, "still failing", max_attempts=2)
    db.refresh(event)
    assert event.status == "failed" and event.last_error == "still failing"
