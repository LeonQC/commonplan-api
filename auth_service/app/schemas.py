from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class IdentityUserRead(BaseModel):
    id: str
    email: EmailStr
    name: str
    avatar_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: IdentityUserRead


class InternalTokenResponse(TokenResponse):
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginCodeExchangeRequest(BaseModel):
    code: str


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot be empty")
        return normalized


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
