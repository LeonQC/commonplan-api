import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Protocol

from fastapi import Depends
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from app.infrastructure.redis import RedisClientDep
from app.models import ApplicationSession
from app.repositories.application_session_repository import (
    ApplicationSessionRepository,
    ApplicationSessionRepositoryDep,
    ApplicationSessionRepositoryError,
)


class SessionStoreUnavailable(Exception):
    """Raised when durable session storage cannot be reached."""


@dataclass(frozen=True)
class SessionData:
    user_id: int | None
    data: dict


class SessionStore(Protocol):
    async def save(
        self,
        session_id: str,
        *,
        user_id: int | None,
        data: dict,
        ttl: int,
    ) -> None: ...

    async def get(self, session_id: str) -> SessionData | None: ...

    async def delete(self, session_id: str) -> None: ...


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _session_key(session_id: str) -> str:
    return f"session:{_session_hash(session_id)}"


class DatabaseBackedSessionStore:
    """Coordinates a PostgreSQL source of truth and expendable Redis cache."""

    def __init__(
        self,
        redis_client: Redis,
        repository: ApplicationSessionRepository,
    ):
        self.redis_client = redis_client
        self.repository = repository

    async def save(
        self,
        session_id: str,
        *,
        user_id: int | None,
        data: dict,
        ttl: int,
    ) -> None:
        record = ApplicationSession(
            session_hash=_session_hash(session_id),
            user_id=user_id,
            data=data,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
        try:
            await run_in_threadpool(self.repository.save, record)
        except ApplicationSessionRepositoryError as exc:
            raise SessionStoreUnavailable from exc
        await self._cache(session_id, SessionData(user_id=user_id, data=data), ttl)

    async def get(self, session_id: str) -> SessionData | None:
        cached = await self._get_cached(session_id)
        if cached is not None:
            return cached

        try:
            record = await run_in_threadpool(
                self.repository.get_by_hash,
                _session_hash(session_id),
            )
        except ApplicationSessionRepositoryError as exc:
            raise SessionStoreUnavailable from exc
        if record is None:
            return None

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            await self.delete(session_id)
            return None

        session = SessionData(user_id=record.user_id, data=record.data)
        await self._cache(session_id, session, remaining)
        return session

    async def delete(self, session_id: str) -> None:
        try:
            record = await run_in_threadpool(
                self.repository.get_by_hash,
                _session_hash(session_id),
            )
            if record is not None:
                await run_in_threadpool(self.repository.delete, record)
        except ApplicationSessionRepositoryError as exc:
            raise SessionStoreUnavailable from exc
        try:
            await self.redis_client.delete(_session_key(session_id))
        except RedisError:
            pass

    async def _get_cached(self, session_id: str) -> SessionData | None:
        try:
            payload = await self.redis_client.get(_session_key(session_id))
        except RedisError:
            return None
        if payload is None:
            return None
        try:
            value = json.loads(payload)
            user_id = value.get("user_id")
            data = value.get("data")
        except (AttributeError, TypeError, json.JSONDecodeError):
            return None
        if user_id is not None and not isinstance(user_id, int):
            return None
        if not isinstance(data, dict):
            return None
        return SessionData(user_id=user_id, data=data)

    async def _cache(
        self,
        session_id: str,
        session: SessionData,
        ttl: int,
    ) -> None:
        payload = json.dumps(
            {"user_id": session.user_id, "data": session.data},
            separators=(",", ":"),
        )
        try:
            await self.redis_client.set(_session_key(session_id), payload, ex=ttl)
        except RedisError:
            pass


def get_session_store(
    redis_client: RedisClientDep,
    repository: ApplicationSessionRepositoryDep,
) -> SessionStore:
    return DatabaseBackedSessionStore(redis_client, repository)


SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
