from typing import Annotated

import httpx
from fastapi import Depends

from app.config import settings
from app.schemas import InternalAuthTokenResponse, LoginRequest, RegisterRequest


class AuthServiceError(Exception):
    def __init__(self, status_code: int, detail: str, retry_after: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


class AuthServiceClient:
    def __init__(self, base_url: str, client_secret: str):
        self.base_url = base_url
        self.auth = httpx.BasicAuth(settings.auth_client_id, client_secret)

    async def register(self, payload: RegisterRequest) -> InternalAuthTokenResponse:
        return await self._token_request("/internal/auth/register", payload.model_dump(mode="json"))

    async def login(self, payload: LoginRequest) -> InternalAuthTokenResponse:
        return await self._token_request("/internal/auth/login", payload.model_dump(mode="json"))

    async def refresh(self, refresh_token: str) -> InternalAuthTokenResponse:
        return await self._token_request(
            "/internal/auth/refresh", {"refresh_token": refresh_token}
        )

    async def exchange(self, code: str) -> InternalAuthTokenResponse:
        return await self._token_request("/internal/auth/exchange", {"code": code})

    async def logout(self, refresh_token: str) -> None:
        await self._request(
            "POST", "/internal/auth/logout", json={"refresh_token": refresh_token}
        )

    async def google_status(self) -> dict[str, bool]:
        response = await self._request("GET", "/auth/google/status")
        return response.json()

    async def _token_request(self, path: str, payload: dict) -> InternalAuthTokenResponse:
        response = await self._request("POST", path, json=payload)
        return InternalAuthTokenResponse.model_validate(response.json())

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=10.0, auth=self.auth
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise AuthServiceError(503, "Authentication service unavailable") from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", "Authentication failed")
            except ValueError:
                detail = "Authentication failed"
            raise AuthServiceError(
                response.status_code, detail, response.headers.get("Retry-After")
            )
        return response


def get_auth_service_client() -> AuthServiceClient:
    return AuthServiceClient(
        settings.auth_internal_url, settings.auth_internal_client_secret
    )


AuthServiceClientDep = Annotated[AuthServiceClient, Depends(get_auth_service_client)]
