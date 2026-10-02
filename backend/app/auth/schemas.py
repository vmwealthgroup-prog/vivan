from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.security import MAX_PASSWORD_BYTES


def _validate_password(v: str) -> str:
    if v.isdigit() or v.isalpha():
        raise ValueError("Password must mix letters and numbers (or symbols) — not letters-only or digits-only.")
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes (bcrypt's limit — "
                          f"non-ASCII characters count as more than one byte each).")
    return v


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = Field(default=None, min_length=6, max_length=6)


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    role: str
    is_email_verified: bool
    is_2fa_enabled: bool

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    requires_2fa: bool
    access_token: str | None = None
    token_type: str = "bearer"
    user: UserPublic | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class Setup2FAResponse(BaseModel):
    secret: str
    otpauth_url: str
    qr_code_png_base64: str


class Confirm2FARequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class Disable2FARequest(BaseModel):
    password: str
