import asyncio

import fakeredis
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.repositories.application_session_repository import (
    SqlAlchemyApplicationSessionRepository,
)
from app.services.session_service import SessionService
from app.stores.session_store import DatabaseBackedSessionStore, SessionData


class InMemorySessionStore:
    def __init__(self):
        self.records: dict[str, SessionData] = {}
        self.last_ttl: int | None = None

    async def save(self, session_id, *, user_id, data, ttl):
        self.records[session_id] = SessionData(user_id=user_id, data=data)
        self.last_ttl = ttl

    async def get(self, session_id):
        return self.records.get(session_id)

    async def delete(self, session_id):
        self.records.pop(session_id, None)


def test_session_service_supports_general_application_state():
    async def scenario() -> None:
        store = InMemorySessionStore()
        service = SessionService(store)

        session_id = await service.create(
            user_id=42,
            data={"workflow": "onboarding", "step": 2},
            ttl=600,
        )

        assert len(session_id) >= 40
        assert store.last_ttl == 600
        assert await service.resolve(session_id) == SessionData(
            user_id=42,
            data={"workflow": "onboarding", "step": 2},
        )
        await service.delete(session_id)
        assert await service.resolve(session_id) is None

    asyncio.run(scenario())


def test_session_service_rejects_invalid_ids_before_store_access():
    async def scenario() -> None:
        store = InMemorySessionStore()
        service = SessionService(store)
        assert await service.resolve(None) is None
        assert await service.resolve("too-short") is None
        assert store.records == {}

    asyncio.run(scenario())


def test_postgres_is_source_of_truth_when_redis_cache_is_empty_or_down():
    class UnavailableRedis:
        async def get(self, _key):
            raise ConnectionError("down")

        async def set(self, _key, _value, **_kwargs):
            raise ConnectionError("down")

        async def delete(self, _key):
            raise ConnectionError("down")

    async def scenario() -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            repository = SqlAlchemyApplicationSessionRepository(db)
            redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
            store = DatabaseBackedSessionStore(redis, repository)
            session_id = "durable-application-session-id-123456789"
            await store.save(
                session_id,
                user_id=None,
                data={"draft_id": "draft-7"},
                ttl=600,
            )
            await redis.flushall()

            assert await store.get(session_id) == SessionData(
                user_id=None,
                data={"draft_id": "draft-7"},
            )
            fallback_store = DatabaseBackedSessionStore(UnavailableRedis(), repository)
            assert await fallback_store.get(session_id) == SessionData(
                user_id=None,
                data={"draft_id": "draft-7"},
            )

    asyncio.run(scenario())
