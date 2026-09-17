import secrets
from typing import Annotated

from fastapi import Depends

from app.config import settings
from app.stores.session_store import SessionData, SessionStore, SessionStoreDep


class SessionService:
    """Owns application session lifecycle rules."""

    def __init__(self, store: SessionStore):
        self.store = store

    async def create(
        self,
        *,
        data: dict,
        user_id: int | None = None,
        ttl: int | None = None,
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        await self.store.save(
            session_id,
            user_id=user_id,
            data=data,
            ttl=ttl or settings.session_max_age_seconds,
        )
        return session_id

    async def resolve(self, session_id: str | None) -> SessionData | None:
        if not session_id or not 20 <= len(session_id) <= 128:
            return None
        return await self.store.get(session_id)

    async def delete(self, session_id: str | None) -> None:
        if session_id:
            await self.store.delete(session_id)


def get_session_service(store: SessionStoreDep) -> SessionService:
    return SessionService(store)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
