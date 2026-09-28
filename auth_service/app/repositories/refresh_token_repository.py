from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import IdentityUser, LoginCode, RefreshToken


class RefreshTokenRepository(Protocol):
    def add(self, token: RefreshToken) -> None: ...

    def get_for_update(self, token_hash: str) -> RefreshToken | None: ...

    def revoke_family(self, family_id: str, revoked_at) -> None: ...

    def revoke_user_tokens(self, user_id: str, revoked_at) -> None: ...

    def user(self, user_id: str) -> IdentityUser | None: ...

    def add_login_code(self, code: LoginCode) -> None: ...

    def login_code_for_update(self, code_hash: str) -> LoginCode | None: ...

    def save_changes(self) -> None: ...


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, token: RefreshToken) -> None:
        self.db.add(token)

    def get_for_update(self, token_hash: str) -> RefreshToken | None:
        return self.db.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )

    def revoke_family(self, family_id: str, revoked_at) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    def revoke_user_tokens(self, user_id: str, revoked_at) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    def user(self, user_id: str) -> IdentityUser | None:
        return self.db.get(IdentityUser, user_id)

    def add_login_code(self, code: LoginCode) -> None:
        self.db.add(code)

    def login_code_for_update(self, code_hash: str) -> LoginCode | None:
        return self.db.scalar(
            select(LoginCode).where(LoginCode.code_hash == code_hash).with_for_update()
        )

    def save_changes(self) -> None:
        self.db.commit()


def get_refresh_token_repository(db: DbSession) -> RefreshTokenRepository:
    return SqlAlchemyRefreshTokenRepository(db)


RefreshTokenRepositoryDep = Annotated[
    RefreshTokenRepository,
    Depends(get_refresh_token_repository),
]
