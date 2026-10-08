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
    github_webhook_secret: str = ""
    github_allowed_owner_id: int | None = None
    github_allowed_owner_login: str = ""
    github_workspace_id: str = ""
    github_hook_id: int | None = None
    object_storage_driver: Literal["local", "s3"] = "local"
    object_storage_local_path: str = "/var/lib/commonplan/attachments"
    object_storage_local_public_url: str = "http://localhost:8000"
    object_storage_signing_secret: str = "local-dev-file-signing-change-me"
    object_storage_endpoint: str = "https://s3.amazonaws.com"
    object_storage_public_endpoint: str = "https://s3.amazonaws.com"
    object_storage_region: str = "us-east-1"
    object_storage_bucket: str = "commonplan-attachments"
    object_storage_access_key: str = "commonplan"
    object_storage_secret_key: str = "commonplan-local-secret"
    attachment_upload_max_bytes: int = 25 * 1024 * 1024
    attachment_url_ttl_seconds: int = 15 * 60
    ingestion_worker_id: str = "ingestion-worker-1"
    ingestion_poll_seconds: float = 1.0
    ingestion_lease_seconds: int = 10 * 60
    ingestion_max_attempts: int = 5
    ingestion_allow_unscanned: bool = True
    ingestion_chunk_tokens: int = 300
    ingestion_chunk_overlap_tokens: int = 50
    ingestion_embedding_provider: Literal["local_hash", "openai"] = "local_hash"
    ingestion_embedding_model: str = "local-hash-v1"
    ingestion_embedding_dimensions: int = 384
    openai_api_key: str = ""
    retrieval_candidate_multiplier: int = 4
    retrieval_parent_max_chars: int = 6000
    retrieval_min_score: float = 0.15

    @model_validator(mode="after")
    def validate_cookie_settings(self) -> "Settings":
        if self.cookie_same_site == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None cookies require COOKIE_SECURE=true")
        if self.ingestion_embedding_dimensions != 384:
            raise ValueError("INGESTION_EMBEDDING_DIMENSIONS must match vector(384)")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)


settings = Settings()
