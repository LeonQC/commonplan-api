from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://zhitong:zhitong@db:5432/zhitong"
    frontend_url: str = "http://localhost:5173"
    redis_url: str = "redis://redis:6379/0"
    auth_issuer: str = "http://localhost:8001"
    auth_audience: str = "zhitong-api"
    auth_client_id: str = "zhitong-web"
    auth_jwks_url: str = "http://auth-service:8001/.well-known/jwks.json"
    auth_internal_url: str = "http://auth-service:8001"
    auth_public_url: str = "http://localhost:8001"
    auth_internal_client_secret: str = "local-dev-bff-client-change-me"
    auth_access_token_max_age_seconds: int = 15 * 60
    refresh_token_max_age_seconds: int = 60 * 60 * 24 * 30
    bff_token_encryption_secret: str = "local-dev-refresh-vault-change-me"
    bff_session_cookie_name: str = "zhitong_web_session"
    cookie_secure: bool = False
    cookie_same_site: Literal["lax", "strict", "none"] = "lax"
    session_max_age_seconds: int = 60 * 60 * 24 * 7

    @model_validator(mode="after")
    def validate_cookie_settings(self) -> "Settings":
        if self.cookie_same_site == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None cookies require COOKIE_SECURE=true")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
