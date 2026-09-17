from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://zhitong:zhitong@db:5432/zhitong_auth"
    )
    frontend_url: str = "http://localhost:5173"
    public_url: str = "http://localhost:8001"
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = "local-dev-auth-state-change-me"
    issuer: str = "http://localhost:8001"
    audience: str = "zhitong-api"
    client_id: str = "zhitong-web"
    internal_client_secret: str = "local-dev-bff-client-change-me"
    bff_callback_url: str = "http://localhost:8000/auth/google/complete"
    login_code_max_age_seconds: int = 60
    signing_algorithm: Literal["RS256"] = "RS256"
    signing_key_id: str = "local-dev-1"
    private_key_path: Path = Path("/var/lib/zhitong-auth/keys/private.pem")
    public_key_path: Path = Path("/var/lib/zhitong-auth/keys/public.pem")
    access_token_max_age_seconds: int = 15 * 60
    refresh_token_max_age_seconds: int = 60 * 60 * 24 * 30
    oauth_state_cookie_name: str = "zhitong_oauth_state"
    oauth_state_max_age_seconds: int = 10 * 60
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 15 * 60
    login_lock_seconds: int = 15 * 60
    cookie_secure: bool = False
    cookie_same_site: Literal["lax", "strict", "none"] = "lax"

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.cookie_same_site == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None cookies require COOKIE_SECURE=true")
        if self.access_token_max_age_seconds > 15 * 60:
            raise ValueError("Access tokens may not live longer than 15 minutes")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
