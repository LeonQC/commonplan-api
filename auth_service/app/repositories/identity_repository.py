from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import ExternalIdentity, IdentityUser, LoginAttempt
from app.repositories.errors import RepositoryConflictError


class IdentityRepository(Protocol):
    def get_user_by_id(self, user_id: str) -> IdentityUser | None: ...

    def get_user_by_email(self, normalized_email: str) -> IdentityUser | None: ...

    def get_user_by_external_identity(
        self, provider: str, subject: str
    ) -> IdentityUser | None: ...

    def add_user(self, user: IdentityUser) -> None: ...

    def add_external_identity(self, identity: ExternalIdentity) -> None: ...

    def refresh_user(self, user: IdentityUser) -> None: ...

    def login_attempt(self, identifier_hash: str) -> LoginAttempt | None: ...

    def add_login_attempt(self, attempt: LoginAttempt) -> None: ...

    def delete_login_attempt(self, attempt: LoginAttempt) -> None: ...

    def save_changes(self) -> None: ...


class SqlAlchemyIdentityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: str) -> IdentityUser | None:
        return self.db.get(IdentityUser, user_id)

    def get_user_by_email(self, normalized_email: str) -> IdentityUser | None:
        return self.db.scalar(
            select(IdentityUser).where(func.lower(IdentityUser.email) == normalized_email)
        )

    def get_user_by_external_identity(
        self, provider: str, subject: str
    ) -> IdentityUser | None:
        return self.db.scalar(
            select(IdentityUser)
            .join(ExternalIdentity, ExternalIdentity.user_id == IdentityUser.id)
            .where(
                ExternalIdentity.provider == provider,
                ExternalIdentity.subject == subject,
            )
        )

    def add_user(self, user: IdentityUser) -> None:
        self.db.add(user)

    def add_external_identity(self, identity: ExternalIdentity) -> None:
        self.db.add(identity)

    def refresh_user(self, user: IdentityUser) -> None:
        self.db.refresh(user)

    def login_attempt(self, identifier_hash: str) -> LoginAttempt | None:
        return self.db.get(LoginAttempt, identifier_hash)

    def add_login_attempt(self, attempt: LoginAttempt) -> None:
        self.db.add(attempt)

    def delete_login_attempt(self, attempt: LoginAttempt) -> None:
        self.db.delete(attempt)

    def save_changes(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RepositoryConflictError from exc


def get_identity_repository(db: DbSession) -> IdentityRepository:
    return SqlAlchemyIdentityRepository(db)


IdentityRepositoryDep = Annotated[IdentityRepository, Depends(get_identity_repository)]
