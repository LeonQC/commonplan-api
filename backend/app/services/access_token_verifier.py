from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends

from app.config import settings


class InvalidAccessToken(Exception):
    pass


class AccessTokenVerificationUnavailable(Exception):
    pass


@dataclass(frozen=True)
class AuthPrincipal:
    issuer: str
    subject: str
    email: str
    name: str
    avatar_url: str | None


class AccessTokenVerifier:
    """Validate Auth Service access JWTs using its published public keys."""

    def __init__(self, jwks_client: jwt.PyJWKClient):
        self.jwks_client = jwks_client

    def verify(self, token: str) -> AuthPrincipal:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != "at+jwt":
                raise InvalidAccessToken
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.auth_audience,
                issuer=settings.auth_issuer,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "sub",
                        "aud",
                        "jti",
                        "client_id",
                    ]
                },
            )
            if claims["client_id"] != settings.auth_client_id:
                raise InvalidAccessToken
            token_lifetime = int(claims["exp"]) - int(claims["iat"])
            if token_lifetime <= 0 or token_lifetime > settings.auth_access_token_max_age_seconds:
                raise InvalidAccessToken
            email = str(claims["email"])
            name = str(claims["name"])
        except jwt.PyJWKClientConnectionError as exc:
            raise AccessTokenVerificationUnavailable from exc
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidAccessToken from exc

        return AuthPrincipal(
            issuer=str(claims["iss"]),
            subject=str(claims["sub"]),
            email=email,
            name=name,
            avatar_url=claims.get("picture"),
        )


@lru_cache
def get_access_token_verifier() -> AccessTokenVerifier:
    return AccessTokenVerifier(
        jwt.PyJWKClient(
            settings.auth_jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
        )
    )


AccessTokenVerifierDep = Annotated[
    AccessTokenVerifier,
    Depends(get_access_token_verifier),
]
