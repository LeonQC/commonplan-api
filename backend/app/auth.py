from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.models import User
from app.services.access_token_verifier import (
    AccessTokenVerificationUnavailable,
    AccessTokenVerifierDep,
    InvalidAccessToken,
)
from app.services.user_service import UserConflict, UserServiceDep


bearer_scheme = HTTPBearer(
    scheme_name="AccessToken",
    description="Short-lived JWT issued by Zhitong Auth Service",
    auto_error=False,
)
AccessTokenCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(bearer_scheme),
]


async def get_current_user(
    credentials: AccessTokenCredentials,
    verifier: AccessTokenVerifierDep,
    user_service: UserServiceDep,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        principal = await run_in_threadpool(verifier.verify, credentials.credentials)
        user = await run_in_threadpool(user_service.provision_identity, principal)
    except InvalidAccessToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccessTokenVerificationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc
    except UserConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Authenticated identity conflicts with an existing profile",
        ) from exc

    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is no longer active",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_self(user_id: int, current_user: CurrentUser) -> User:
    """Current baseline policy until workspace administrator roles exist."""
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only modify your own profile",
        )
    return current_user


SelfUser = Annotated[User, Depends(require_self)]
