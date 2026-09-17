import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import User
from app.repositories.user_repository import SqlAlchemyUserRepository


@pytest.fixture
def repository():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SqlAlchemyUserRepository(db), db


def test_repository_owns_case_insensitive_email_query(repository):
    users, db = repository
    user = User(
        email="ADA@EXAMPLE.COM", name="Ada", auth_issuer="issuer", auth_subject="ada"
    )
    users.add(user)
    db.commit()

    found = users.get_by_email("ada@example.com")

    assert found is not None
    assert found.id == user.id


def test_repository_filters_soft_deleted_users(repository):
    users, db = repository
    active = User(
        email="active@example.com", name="Active", auth_issuer="issuer", auth_subject="active"
    )
    deleted = User(
        email="deleted@example.com",
        name="Deleted",
        auth_issuer="issuer",
        auth_subject="deleted",
        is_deleted=True,
    )
    users.add(active)
    users.add(deleted)
    db.commit()

    assert [user.id for user in users.list()] == [active.id]
    assert [user.id for user in users.list(include_deleted=True)] == [
        active.id,
        deleted.id,
    ]
