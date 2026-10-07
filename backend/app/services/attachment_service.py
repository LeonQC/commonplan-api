from datetime import datetime, timezone
from pathlib import PurePath
from typing import Annotated
import re
import uuid

from fastapi import Depends

from app.config import settings
from app.infrastructure.object_storage import ObjectStorage, ObjectStorageDep
from app.models import FileAsset, IssueAttachment, OutboxEvent, ProjectAttachment, User
from app.repositories.attachment_repository import AttachmentRepository, AttachmentRepositoryDep
from app.repositories.errors import RepositoryConflictError
from app.services.workspace_service import WorkspaceService, WorkspaceServiceDep


class AttachmentNotFound(Exception): pass
class AttachmentForbidden(Exception): pass
class AttachmentConflict(Exception): pass
class AttachmentValidationError(Exception): pass
class AttachmentStorageError(Exception): pass


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/json",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/markdown",
    "text/plain",
}


class AttachmentService:
    def __init__(
        self,
        repository: AttachmentRepository,
        workspaces: WorkspaceService,
        storage: ObjectStorage,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.storage = storage

    def list_issue(self, user: User, workspace_id: str, key: str) -> list[FileAsset]:
        issue = self._issue(user, workspace_id, key)
        return self.repository.issue_files(issue.id)

    def initiate_issue(
        self, user: User, workspace_id: str, key: str, *, filename: str,
        content_type: str, byte_size: int, sha256: str | None,
    ) -> tuple[FileAsset, str]:
        issue = self._issue(user, workspace_id, key)
        asset = self._asset(user, workspace_id, filename, content_type, byte_size, sha256)
        self.repository.add(asset)
        self.repository.add(IssueAttachment(
            issue_id=issue.id, file_asset_id=asset.id, added_by_user_id=user.id
        ))
        self._commit()
        self.repository.refresh(asset)
        return asset, self.storage.upload_url(
            asset.storage_key, asset.content_type, asset.byte_size
        )

    def list_project(
        self, user: User, workspace_id: str, team_id: str, project_id: str,
    ) -> list[FileAsset]:
        project = self._project(user, workspace_id, team_id, project_id)
        return self.repository.project_files(project.id)

    def initiate_project(
        self, user: User, workspace_id: str, team_id: str, project_id: str, *,
        filename: str, content_type: str, byte_size: int, sha256: str | None,
    ) -> tuple[FileAsset, str]:
        project = self._project(user, workspace_id, team_id, project_id)
        asset = self._asset(user, workspace_id, filename, content_type, byte_size, sha256)
        self.repository.add(asset)
        self.repository.add(ProjectAttachment(
            project_id=project.id, file_asset_id=asset.id, added_by_user_id=user.id
        ))
        self._commit()
        self.repository.refresh(asset)
        return asset, self.storage.upload_url(
            asset.storage_key, asset.content_type, asset.byte_size
        )

    def complete(self, user: User, workspace_id: str, file_id: str) -> FileAsset:
        asset = self._file_with_access(user, workspace_id, file_id, for_update=True)
        if asset.upload_status == "ready":
            return asset
        try:
            stored = self.storage.stat(asset.storage_key)
        except Exception as exc:
            raise AttachmentStorageError("Object storage is unavailable") from exc
        if stored is None:
            raise AttachmentConflict("Upload has not reached object storage")
        if stored.byte_size != asset.byte_size:
            raise AttachmentConflict("Uploaded file size does not match the initiated upload")
        asset.upload_status = "ready"
        asset.ready_at = datetime.now(timezone.utc)
        self.repository.add(self._event(asset, "file.ready"))
        self._commit()
        self.repository.refresh(asset)
        return asset

    def download_url(self, user: User, workspace_id: str, file_id: str) -> str:
        asset = self._file_with_access(user, workspace_id, file_id)
        if asset.upload_status != "ready":
            raise AttachmentConflict("File is not ready")
        return self.storage.download_url(asset.storage_key, asset.original_filename)

    def delete(self, user: User, workspace_id: str, file_id: str) -> None:
        asset = self._file_with_access(user, workspace_id, file_id, for_update=True)
        try:
            self.storage.delete(asset.storage_key)
        except Exception as exc:
            raise AttachmentStorageError("Object storage is unavailable") from exc
        asset.upload_status = "deleted"
        asset.deleted_at = datetime.now(timezone.utc)
        self.repository.add(self._event(asset, "file.deleted"))
        self._commit()

    def _issue(self, user: User, workspace_id: str, key: str):
        issue = self.repository.issue_by_key(workspace_id, key.upper())
        if issue is None:
            raise AttachmentNotFound
        self._team_access(user, workspace_id, issue.team_id)
        return issue

    def _project(self, user: User, workspace_id: str, team_id: str, project_id: str):
        self._team_access(user, workspace_id, team_id)
        project = self.repository.project(project_id)
        if project is None or project.team_id != team_id:
            raise AttachmentNotFound
        return project

    def _file_with_access(
        self, user: User, workspace_id: str, file_id: str, *, for_update: bool = False,
    ) -> FileAsset:
        asset = self.repository.file(file_id, for_update=for_update)
        scope = self.repository.file_scope(file_id) if asset else None
        if asset is None or scope is None or asset.workspace_id != workspace_id or scope[0] != workspace_id:
            raise AttachmentNotFound
        self._team_access(user, workspace_id, scope[1])
        return asset

    def _team_access(self, user: User, workspace_id: str, team_id: str) -> None:
        try:
            self.workspaces.get_team(user, workspace_id, team_id)
        except Exception as exc:
            if exc.__class__.__name__.endswith("NotFound"):
                raise AttachmentNotFound from exc
            raise AttachmentForbidden from exc

    @staticmethod
    def _asset(
        user: User, workspace_id: str, filename: str, content_type: str,
        byte_size: int, sha256: str | None,
    ) -> FileAsset:
        normalized = filename.strip()
        if not normalized or PurePath(normalized).name != normalized or len(normalized) > 255:
            raise AttachmentValidationError("Filename is invalid")
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise AttachmentValidationError("File type is not allowed")
        if byte_size < 1 or byte_size > settings.attachment_upload_max_bytes:
            raise AttachmentValidationError(
                f"File size must be between 1 and {settings.attachment_upload_max_bytes} bytes"
            )
        if sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            raise AttachmentValidationError("SHA-256 must be 64 hexadecimal characters")
        file_id = str(uuid.uuid4())
        return FileAsset(
            id=file_id,
            workspace_id=workspace_id,
            uploaded_by_user_id=user.id,
            original_filename=normalized,
            storage_key=f"workspaces/{workspace_id}/{file_id}",
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256.lower() if sha256 else None,
            upload_status="pending",
            scan_status="not_configured",
        )

    @staticmethod
    def _event(asset: FileAsset, event_type: str) -> OutboxEvent:
        return OutboxEvent(
            id=str(uuid.uuid4()), workspace_id=asset.workspace_id,
            aggregate_type="file_asset", aggregate_id=asset.id, event_type=event_type,
            payload={
                "file_id": asset.id, "storage_key": asset.storage_key,
                "content_type": asset.content_type, "byte_size": asset.byte_size,
            },
        )

    def _commit(self) -> None:
        try:
            self.repository.save_changes()
        except RepositoryConflictError as exc:
            raise AttachmentConflict("Attachment state changed; retry the request") from exc


def get_attachment_service(
    repository: AttachmentRepositoryDep,
    workspaces: WorkspaceServiceDep,
    storage: ObjectStorageDep,
) -> AttachmentService:
    return AttachmentService(repository, workspaces, storage)


AttachmentServiceDep = Annotated[AttachmentService, Depends(get_attachment_service)]
