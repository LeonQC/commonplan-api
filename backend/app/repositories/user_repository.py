from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import User


class UserRepository(Protocol):
    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_email(self, normalized_email: str) -> User | None: ...

    def get_by_identity(self, issuer: str, subject: str) -> User | None: ...

    def list(self, *, include_deleted: bool = False) -> list[User]: ...

    def add(self, user: User) -> None: ...

    def refresh(self, user: User) -> None: ...


class SqlAlchemyUserRepository:
    """SQLAlchemy implementation of user persistence queries."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, normalized_email: str) -> User | None:
        return self.db.scalar(
            select(User).where(func.lower(User.email) == normalized_email)
        )

    def get_by_identity(self, issuer: str, subject: str) -> User | None:
        return self.db.scalar(
            select(User).where(
                User.auth_issuer == issuer,
                User.auth_subject == subject,
            )
        )

    def list(self, *, include_deleted: bool = False) -> list[User]:
        stmt = select(User).order_by(User.id)
        if not include_deleted:
            stmt = stmt.where(User.is_deleted.is_(False))
        return list(self.db.scalars(stmt))

    def add(self, user: User) -> None:
        self.db.add(user)

    def refresh(self, user: User) -> None:
        self.db.refresh(user)


def get_user_repository(db: DbSession) -> UserRepository:
    return SqlAlchemyUserRepository(db)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
