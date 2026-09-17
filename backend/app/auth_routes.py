from typing import NoReturn
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.schemas import AuthTokenResponse, LoginRequest, RegisterRequest
from app.services.auth_service_client import (
    AuthServiceClientDep,
    AuthServiceError,
)
from app.services.browser_auth_session_service import (
    BrowserAuthSessionServiceDep,
    InvalidBrowserSession,
)


def verify_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.frontend_url.rstrip("/"):
        raise HTTPException(403, detail="Untrusted browser origin")


router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    dependencies=[Depends(verify_browser_origin)],
)


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        settings.bff_session_cookie_name,
        session_id,
        max_age=settings.refresh_token_max_age_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_same_site,
        path="/auth",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.bff_session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_same_site,
        path="/auth",
    )


def public_token_response(token) -> AuthTokenResponse:
    return AuthTokenResponse.model_validate(token.model_dump(exclude={"refresh_token"}))


def raise_auth_error(exc: AuthServiceError) -> NoReturn:
    headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
    raise HTTPException(exc.status_code, detail=exc.detail, headers=headers) from exc


def cleared_error_response(status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    clear_session_cookie(response)
    return response


def frontend_url_with_error(error_code: str) -> str:
    parts = urlsplit(settings.frontend_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["auth_error"] = error_code
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@router.get("/google/status")
async def google_status(auth_client: AuthServiceClientDep) -> dict[str, bool]:
    try:
        return await auth_client.google_status()
    except AuthServiceError as exc:
        raise_auth_error(exc)


@router.get("/google/login")
def google_login() -> RedirectResponse:
    return RedirectResponse(f"{settings.auth_public_url}/auth/google/login")


@router.get("/google/complete")
async def google_complete(
    code: str,
    auth_client: AuthServiceClientDep,
    sessions: BrowserAuthSessionServiceDep,
) -> RedirectResponse:
    try:
        token = await auth_client.exchange(code)
    except AuthServiceError:
        return RedirectResponse(frontend_url_with_error("oauth_failed"), status_code=302)
    session_id = sessions.create(
        auth_subject=token.user.id, refresh_token=token.refresh_token
    )
    response = RedirectResponse(settings.frontend_url, status_code=302)
    set_session_cookie(response, session_id)
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/register", response_model=AuthTokenResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    response: Response,
    auth_client: AuthServiceClientDep,
    sessions: BrowserAuthSessionServiceDep,
) -> AuthTokenResponse | Response:
    try:
        token = await auth_client.register(payload)
    except AuthServiceError as exc:
        raise_auth_error(exc)
    session_id = sessions.create(
        auth_subject=token.user.id, refresh_token=token.refresh_token
    )
    set_session_cookie(response, session_id)
    return public_token_response(token)


@router.post("/login", response_model=AuthTokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    auth_client: AuthServiceClientDep,
    sessions: BrowserAuthSessionServiceDep,
) -> AuthTokenResponse:
    try:
        token = await auth_client.login(payload)
    except AuthServiceError as exc:
        raise_auth_error(exc)
    session_id = sessions.create(
        auth_subject=token.user.id, refresh_token=token.refresh_token
    )
    set_session_cookie(response, session_id)
    return public_token_response(token)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh(
    response: Response,
    auth_client: AuthServiceClientDep,
    sessions: BrowserAuthSessionServiceDep,
    session_id: str | None = Cookie(default=None, alias=settings.bff_session_cookie_name),
) -> AuthTokenResponse:
    try:
        record, refresh_token = sessions.load_for_refresh(session_id)
    except InvalidBrowserSession:
        return cleared_error_response(401, "Invalid or expired browser session")
    try:
        token = await auth_client.refresh(refresh_token)
    except AuthServiceError as exc:
        if exc.status_code == 401:
            sessions.revoke(record)
            return cleared_error_response(exc.status_code, exc.detail)
        raise_auth_error(exc)
    new_session_id = sessions.rotate(
        record, refresh_token=token.refresh_token, auth_subject=token.user.id
    )
    set_session_cookie(response, new_session_id)
    return public_token_response(token)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    auth_client: AuthServiceClientDep,
    sessions: BrowserAuthSessionServiceDep,
    session_id: str | None = Cookie(default=None, alias=settings.bff_session_cookie_name),
) -> None:
    try:
        record, refresh_token = sessions.load_for_refresh(session_id)
    except InvalidBrowserSession:
        clear_session_cookie(response)
        return
    try:
        await auth_client.logout(refresh_token)
    except AuthServiceError:
        pass
    sessions.revoke(record)
    clear_session_cookie(response)
