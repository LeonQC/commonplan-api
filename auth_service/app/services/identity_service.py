import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.config import settings
from app.models import ExternalIdentity, IdentityUser, LoginAttempt
from app.passwords import hash_password, verify_password
from app.repositories.identity_repository import (
    IdentityRepository,
    IdentityRepositoryDep,
)


class IdentityConflict(Exception):
    pass


class LoginRateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def normalize_email(email: str) -> str:
    return email.strip().lower()


class IdentityService:
    def __init__(self, repository: IdentityRepository, db: Session):
        self.repository = repository
        self.db = db

    def get_active_by_id(self, user_id: str) -> IdentityUser | None:
        user = self.repository.get_user_by_id(user_id)
        if user is None or not user.is_active:
            return None
        return user

    def register(self, *, email: str, name: str, password: str) -> IdentityUser:
        normalized = normalize_email(email)
        if self.repository.get_user_by_email(normalized) is not None:
            raise IdentityConflict
        user = IdentityUser(
            id=str(uuid.uuid4()),
            email=normalized,
            name=name,
            password_hash=hash_password(password),
        )
        self.repository.add_user(user)
        return self._commit(user)

    def authenticate_password(self, *, email: str, password: str) -> IdentityUser | None:
        normalized = normalize_email(email)
        now = datetime.now(timezone.utc)
        identifier_hash = hashlib.sha256(normalized.encode()).hexdigest()
        attempt = self.db.get(LoginAttempt, identifier_hash)
        if attempt is not None and attempt.locked_until is not None:
            locked_until = attempt.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > now:
                raise LoginRateLimited(max(1, int((locked_until - now).total_seconds())))

        user = self.repository.get_user_by_email(normalized)
        password_matches = verify_password(
            password,
            user.password_hash if user is not None else None,
        )
        if (
            user is None
            or not user.is_active
            or user.password_hash is None
            or not password_matches
        ):
            self._record_login_failure(identifier_hash, attempt, now)
            return None
        if attempt is not None:
            self.db.delete(attempt)
            self.db.commit()
        return user

    def _record_login_failure(
        self,
        identifier_hash: str,
        attempt: LoginAttempt | None,
        now: datetime,
    ) -> None:
        window_start = now - timedelta(seconds=settings.login_failure_window_seconds)
        if attempt is None:
            attempt = LoginAttempt(
                identifier_hash=identifier_hash,
                failed_attempts=0,
                window_started_at=now,
            )
            self.db.add(attempt)
        else:
            started_at = attempt.window_started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if started_at < window_start:
                attempt.failed_attempts = 0
                attempt.window_started_at = now
                attempt.locked_until = None

        attempt.failed_attempts += 1
        if attempt.failed_attempts >= settings.login_failure_limit:
            attempt.locked_until = now + timedelta(seconds=settings.login_lock_seconds)
        self.db.commit()

    def upsert_google_identity(
        self,
        *,
        email: str,
        subject: str,
        name: str,
        avatar_url: str | None,
    ) -> IdentityUser:
        user = self.repository.get_user_by_external_identity("google", subject)
        if user is None:
            user = self.repository.get_user_by_email(normalize_email(email))

        if user is None:
            user = IdentityUser(
                id=str(uuid.uuid4()),
                email=normalize_email(email),
                name=name,
                avatar_url=avatar_url,
            )
            self.repository.add_user(user)
            self._commit(user)

        existing = self.repository.get_user_by_external_identity("google", subject)
        if existing is None:
            self.repository.add_external_identity(
                ExternalIdentity(provider="google", subject=subject, user_id=user.id)
            )
        user.name = name
        user.avatar_url = avatar_url
        user.is_active = True
        return self._commit(user)

    def _commit(self, user: IdentityUser) -> IdentityUser:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise IdentityConflict from exc
        self.repository.refresh_user(user)
        return user


def get_identity_service(
    repository: IdentityRepositoryDep,
    db: DbSession,
) -> IdentityService:
    return IdentityService(repository, db)


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]
