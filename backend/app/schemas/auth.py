from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import password_policy_errors
from app.schemas.common import ORM


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class UserOut(ORM):
    id: str
    email: str
    full_name: str
    role: str
    org_id: str
    department_id: str | None
    is_active: bool
    totp_enabled: bool
    leaderboard_opt_in: bool
    last_login_at: datetime | None = None
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    org_name: str
    csrf_token: str
    access_token: str | None = Field(
        default=None, description="Only returned when ?include_token=true (for API clients/tests)")
    demo_mode: bool


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        errors = password_policy_errors(v)
        if errors:
            raise ValueError("Password needs " + ", ".join(errors))
        return v


class InviteAccept(BaseModel):
    code: str = Field(min_length=10, max_length=100)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=128)

    @field_validator("password")
    @classmethod
    def _policy(cls, v: str) -> str:
        errors = password_policy_errors(v)
        if errors:
            raise ValueError("Password needs " + ", ".join(errors))
        return v


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpVerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
