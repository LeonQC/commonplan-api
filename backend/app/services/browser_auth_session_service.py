import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DbSession
from app.models import BrowserAuthSession
from app.repositories.browser_auth_session_repository import (
    BrowserAuthSessionRepository,
    BrowserAuthSessionRepositoryDep,
)


class InvalidBrowserSession(Exception):
    pass


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class BrowserAuthSessionService:
    def __init__(
        self,
        repository: BrowserAuthSessionRepository,
        db: Session,
    ):
        self.repository = repository
        self.db = db
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.bff_token_encryption_secret.encode("utf-8")).digest()
        )
        self.cipher = Fernet(key)

    def create(self, *, auth_subject: str, refresh_token: str) -> str:
        session_id = secrets.token_urlsafe(32)
        self.repository.add(
            BrowserAuthSession(
                session_hash=hash_session_id(session_id),
                auth_subject=auth_subject,
                encrypted_refresh_token=self._encrypt(refresh_token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=settings.refresh_token_max_age_seconds),
            )
        )
        self.db.commit()
        return session_id

    def load_for_refresh(self, session_id: str | None) -> tuple[BrowserAuthSession, str]:
        if not session_id:
            raise InvalidBrowserSession
        record = self.repository.get_for_update(hash_session_id(session_id))
        now = datetime.now(timezone.utc)
        if record is None or record.revoked_at is not None:
            raise InvalidBrowserSession
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            record.revoked_at = now
            self.db.commit()
            raise InvalidBrowserSession
        try:
            refresh_token = self.cipher.decrypt(
                record.encrypted_refresh_token.encode("ascii")
            ).decode("utf-8")
        except InvalidToken as exc:
            record.revoked_at = now
            self.db.commit()
            raise InvalidBrowserSession from exc
        return record, refresh_token

    def rotate(
        self, record: BrowserAuthSession, *, refresh_token: str, auth_subject: str
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        record.session_hash = hash_session_id(session_id)
        record.auth_subject = auth_subject
        record.encrypted_refresh_token = self._encrypt(refresh_token)
        record.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.refresh_token_max_age_seconds
        )
        self.db.commit()
        return session_id

    def revoke(self, record: BrowserAuthSession) -> None:
        record.revoked_at = datetime.now(timezone.utc)
        self.db.commit()

    def _encrypt(self, refresh_token: str) -> str:
        return self.cipher.encrypt(refresh_token.encode("utf-8")).decode("ascii")


def get_browser_auth_session_service(
    repository: BrowserAuthSessionRepositoryDep,
    db: DbSession,
) -> BrowserAuthSessionService:
    return BrowserAuthSessionService(repository, db)


BrowserAuthSessionServiceDep = Annotated[
    BrowserAuthSessionService,
    Depends(get_browser_auth_session_service),
]
