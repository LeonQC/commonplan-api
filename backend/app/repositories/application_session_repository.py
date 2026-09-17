from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import ApplicationSession


class ApplicationSessionRepositoryError(Exception):
    pass


class ApplicationSessionRepository(Protocol):
    def get_by_hash(self, session_hash: str) -> ApplicationSession | None: ...

    def save(self, record: ApplicationSession) -> None: ...

    def delete(self, record: ApplicationSession) -> None: ...


class SqlAlchemyApplicationSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_hash(self, session_hash: str) -> ApplicationSession | None:
        try:
            return self.db.scalar(
                select(ApplicationSession).where(
                    ApplicationSession.session_hash == session_hash
                )
            )
        except SQLAlchemyError as exc:
            raise ApplicationSessionRepositoryError from exc

    def save(self, record: ApplicationSession) -> None:
        try:
            self.db.add(record)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise ApplicationSessionRepositoryError from exc

    def delete(self, record: ApplicationSession) -> None:
        try:
            self.db.delete(record)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise ApplicationSessionRepositoryError from exc


def get_application_session_repository(
    db: DbSession,
) -> ApplicationSessionRepository:
    return SqlAlchemyApplicationSessionRepository(db)


ApplicationSessionRepositoryDep = Annotated[
    ApplicationSessionRepository,
    Depends(get_application_session_repository),
]
