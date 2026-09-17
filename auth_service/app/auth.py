import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)

from app.config import settings
from app.models import IdentityUser
from app.services.identity_service import IdentityServiceDep
from app.services.token_service import (
    InvalidAccessToken,
    TokenServiceDep,
)


bearer_scheme = HTTPBearer(
    scheme_name="AccessToken",
    description="Short-lived JWT issued by Zhitong Auth Service",
    auto_error=False,
)
AccessTokenCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(bearer_scheme),
]


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_identity(
    credentials: AccessTokenCredentials,
    token_service: TokenServiceDep,
    identity_service: IdentityServiceDep,
) -> IdentityUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Authentication required")
    try:
        user_id = token_service.decode_access_token(credentials.credentials)
    except InvalidAccessToken as exc:
        raise unauthorized("Invalid or expired access token") from exc
    user = identity_service.get_active_by_id(user_id)
    if user is None:
        raise unauthorized("Account is no longer active")
    return user


CurrentIdentity = Annotated[IdentityUser, Depends(get_current_identity)]


internal_client_scheme = HTTPBasic(
    scheme_name="ConfidentialClient",
    description="HTTP Basic authentication for the Zhitong Web BFF",
    auto_error=False,
)
InternalClientCredentials = Annotated[
    HTTPBasicCredentials | None,
    Security(internal_client_scheme),
]


def require_internal_client(credentials: InternalClientCredentials) -> None:
    valid_id = credentials is not None and secrets.compare_digest(
        credentials.username, settings.client_id
    )
    valid_secret = credentials is not None and secrets.compare_digest(
        credentials.password, settings.internal_client_secret
    )
    if not (valid_id and valid_secret):
        raise HTTPException(status_code=401, detail="Invalid service client credentials")


InternalClient = Annotated[None, Depends(require_internal_client)]
