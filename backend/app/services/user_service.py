from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import User
from app.repositories.user_repository import UserRepository, UserRepositoryDep
from app.services.access_token_verifier import AuthPrincipal


class UserConflict(Exception):
    """Raised when a user write violates a uniqueness constraint."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserService:
    """Owns user business rules and transaction boundaries."""

    def __init__(self, repository: UserRepository, db: Session):
        self.repository = repository
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.repository.get_by_id(user_id)

    def get_active_by_id(self, user_id: int) -> User | None:
        user = self.get_by_id(user_id)
        if user is None or user.is_deleted:
            return None
        return user

    def get_by_email(self, email: str) -> User | None:
        return self.repository.get_by_email(normalize_email(email))

    def get_by_identity(self, issuer: str, subject: str) -> User | None:
        return self.repository.get_by_identity(issuer, subject)

    def list(self, *, include_deleted: bool = False) -> list[User]:
        return self.repository.list(include_deleted=include_deleted)

    def create(
        self,
        *,
        email: str,
        name: str,
        auth_issuer: str,
        auth_subject: str,
        avatar_url: str | None = None,
    ) -> User:
        user = User(
            email=normalize_email(email),
            name=name,
            auth_issuer=auth_issuer,
            auth_subject=auth_subject,
            avatar_url=avatar_url,
        )
        self.repository.add(user)
        return self._commit(user)

    def update(self, user: User, changes: dict[str, Any]) -> User:
        if "email" in changes:
            changes["email"] = normalize_email(str(changes["email"]))
        for key, value in changes.items():
            setattr(user, key, value)
        return self._commit(user)

    def soft_delete(self, user: User) -> None:
        user.is_deleted = True
        self._commit(user)

    def provision_identity(self, principal: AuthPrincipal) -> User:
        user = self.get_by_identity(principal.issuer, principal.subject)
        if user is None:
            legacy_or_conflicting = self.get_by_email(principal.email)
            if legacy_or_conflicting is not None:
                if legacy_or_conflicting.auth_subject is not None:
                    raise UserConflict
                user = legacy_or_conflicting
                user.auth_issuer = principal.issuer
                user.auth_subject = principal.subject
            else:
                return self.create(
                    email=principal.email,
                    name=principal.name,
                    auth_issuer=principal.issuer,
                    auth_subject=principal.subject,
                    avatar_url=principal.avatar_url,
                )

        user.name = principal.name
        user.avatar_url = principal.avatar_url
        if normalize_email(user.email) != normalize_email(principal.email):
            other = self.get_by_email(principal.email)
            if other is not None and other.id != user.id:
                raise UserConflict
            user.email = normalize_email(principal.email)
        return self._commit(user)

    def _commit(self, user: User) -> User:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise UserConflict from exc
        self.repository.refresh(user)
        return user


def get_user_service(
    repository: UserRepositoryDep,
    db: DbSession,
) -> UserService:
    return UserService(repository, db)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
