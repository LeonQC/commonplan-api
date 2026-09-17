import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DbSession
from app.models import IdentityUser, LoginCode, RefreshToken
from app.repositories.refresh_token_repository import (
    RefreshTokenRepository,
    RefreshTokenRepositoryDep,
)
from app.signing_keys import SigningKeys, get_signing_keys


class InvalidAccessToken(Exception):
    pass


class InvalidRefreshToken(Exception):
    pass


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_login_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class TokenService:
    def __init__(
        self,
        repository: RefreshTokenRepository,
        db: Session,
        signing_keys: SigningKeys,
    ):
        self.repository = repository
        self.db = db
        self.signing_keys = signing_keys

    def issue_pair(
        self,
        user: IdentityUser,
        *,
        family_id: str | None = None,
    ) -> TokenPair:
        pair, refresh_record = self._build_pair(
            user,
            now=datetime.now(timezone.utc),
            family_id=family_id or str(uuid.uuid4()),
        )
        self.repository.add(refresh_record)
        self.db.commit()
        return pair

    def rotate(self, raw_refresh: str | None) -> tuple[str, TokenPair]:
        if not raw_refresh:
            raise InvalidRefreshToken
        now = datetime.now(timezone.utc)
        current = self.repository.get_for_update(hash_refresh_token(raw_refresh))
        if current is None:
            raise InvalidRefreshToken
        if current.revoked_at is not None:
            self.repository.revoke_family(current.family_id, now)
            self.db.commit()
            raise InvalidRefreshToken
        expires_at = current.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            current.revoked_at = now
            self.db.commit()
            raise InvalidRefreshToken

        user_id = current.user_id
        family_id = current.family_id
        current.revoked_at = now
        user = self.db.get(IdentityUser, user_id)
        if user is None or not user.is_active:
            self.repository.revoke_family(family_id, now)
            self.db.commit()
            raise InvalidRefreshToken

        pair, replacement = self._build_pair(user, now=now, family_id=family_id)
        self.repository.add(replacement)
        current.replaced_by_hash = hash_refresh_token(pair.refresh_token)
        self.db.commit()
        return user_id, pair

    def revoke(self, raw_refresh: str | None) -> None:
        if not raw_refresh:
            return
        current = self.repository.get_for_update(hash_refresh_token(raw_refresh))
        if current is not None and current.revoked_at is None:
            current.revoked_at = datetime.now(timezone.utc)
            self.db.commit()

    def issue_login_code(self, user: IdentityUser) -> str:
        raw_code = secrets.token_urlsafe(32)
        self.db.add(
            LoginCode(
                code_hash=hash_login_code(raw_code),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=settings.login_code_max_age_seconds),
            )
        )
        self.db.commit()
        return raw_code

    def exchange_login_code(self, raw_code: str) -> tuple[IdentityUser, TokenPair]:
        now = datetime.now(timezone.utc)
        record = self.db.scalar(
            select(LoginCode)
            .where(LoginCode.code_hash == hash_login_code(raw_code))
            .with_for_update()
        )
        if record is None or record.used_at is not None:
            raise InvalidRefreshToken
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise InvalidRefreshToken
        user = self.db.get(IdentityUser, record.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshToken
        record.used_at = now
        pair, refresh_record = self._build_pair(
            user, now=now, family_id=str(uuid.uuid4())
        )
        self.repository.add(refresh_record)
        self.db.commit()
        return user, pair

    def decode_access_token(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != "at+jwt" or header.get("kid") != self.signing_keys.key_id:
                raise InvalidAccessToken
            claims = jwt.decode(
                token,
                self.signing_keys.public_pem,
                algorithms=[settings.signing_algorithm],
                audience=settings.audience,
                issuer=settings.issuer,
                options={"require": ["exp", "iat", "iss", "sub", "aud", "jti"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidAccessToken from exc
        return str(claims["sub"])

    def _encode_access_token(self, user: IdentityUser, now: datetime) -> str:
        return jwt.encode(
            {
                "iss": settings.issuer,
                "sub": user.id,
                "aud": settings.audience,
                "client_id": settings.client_id,
                "email": user.email,
                "name": user.name,
                "picture": user.avatar_url,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + timedelta(seconds=settings.access_token_max_age_seconds),
            },
            self.signing_keys.private_pem,
            algorithm=settings.signing_algorithm,
            headers={"kid": self.signing_keys.key_id, "typ": "at+jwt"},
        )

    def _build_pair(
        self,
        user: IdentityUser,
        *,
        now: datetime,
        family_id: str,
    ) -> tuple[TokenPair, RefreshToken]:
        raw_refresh = secrets.token_urlsafe(48)
        return (
            TokenPair(
                access_token=self._encode_access_token(user, now),
                refresh_token=raw_refresh,
                access_expires_in=settings.access_token_max_age_seconds,
            ),
            RefreshToken(
                token_hash=hash_refresh_token(raw_refresh),
                family_id=family_id,
                user_id=user.id,
                expires_at=now + timedelta(seconds=settings.refresh_token_max_age_seconds),
            ),
        )


def get_token_service(
    repository: RefreshTokenRepositoryDep,
    db: DbSession,
    signing_keys: Annotated[SigningKeys, Depends(get_signing_keys)],
) -> TokenService:
    return TokenService(repository, db, signing_keys)


TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
