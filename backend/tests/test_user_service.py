import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.repositories.user_repository import SqlAlchemyUserRepository
from app.services.user_service import UserConflict, UserService
from app.services.access_token_verifier import AuthPrincipal


@pytest.fixture
def users():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield UserService(SqlAlchemyUserRepository(db), db)


def test_create_normalizes_email_and_rejects_case_insensitive_duplicate(users):
    user = users.create(
        email="ADA@EXAMPLE.COM",
        name="Ada",
        auth_issuer="https://auth.example.com",
        auth_subject="subject-1",
    )

    assert user.email == "ada@example.com"

    with pytest.raises(UserConflict):
        users.create(
            email="ada@example.com",
            name="Another Ada",
            auth_issuer="https://auth.example.com",
            auth_subject="subject-2",
        )


def test_user_lifecycle_is_owned_by_service(users):
    first = users.create(
        email="first@example.com", name="First", auth_issuer="issuer", auth_subject="first"
    )
    second = users.create(
        email="second@example.com", name="Second", auth_issuer="issuer", auth_subject="second"
    )

    updated = users.update(
        first,
        {"email": "FIRST.UPDATED@EXAMPLE.COM", "name": "Updated"},
    )
    users.soft_delete(second)

    assert updated.email == "first.updated@example.com"
    assert updated.name == "Updated"
    assert users.get_active_by_id(second.id) is None
    assert [user.id for user in users.list()] == [first.id]
    assert [user.id for user in users.list(include_deleted=True)] == [
        first.id,
        second.id,
    ]


def test_identity_is_provisioned_by_immutable_issuer_and_subject(users):
    principal = AuthPrincipal(
        issuer="https://auth.example.com",
        subject="stable-subject",
        email="linked@example.com",
        name="Identity Name",
        avatar_url="https://example.com/avatar.png",
    )

    first = users.provision_identity(principal)
    second = users.provision_identity(principal)

    assert first.id == second.id
    assert second.auth_subject == "stable-subject"
    assert second.avatar_url == "https://example.com/avatar.png"
