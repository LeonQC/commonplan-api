from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import BrowserAuthSession


class BrowserAuthSessionRepository(Protocol):
    def add(self, session: BrowserAuthSession) -> None: ...

    def get_for_update(self, session_hash: str) -> BrowserAuthSession | None: ...


class SqlAlchemyBrowserAuthSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, session: BrowserAuthSession) -> None:
        self.db.add(session)

    def get_for_update(self, session_hash: str) -> BrowserAuthSession | None:
        return self.db.scalar(
            select(BrowserAuthSession)
            .where(BrowserAuthSession.session_hash == session_hash)
            .with_for_update()
        )


def get_browser_auth_session_repository(
    db: DbSession,
) -> BrowserAuthSessionRepository:
    return SqlAlchemyBrowserAuthSessionRepository(db)


BrowserAuthSessionRepositoryDep = Annotated[
    BrowserAuthSessionRepository,
    Depends(get_browser_auth_session_repository),
]
