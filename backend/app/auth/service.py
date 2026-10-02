"""
VM ALGO — Auth service layer
================================
All business logic lives here, independent of FastAPI, so it's directly
unit-testable (see app/tests/test_auth.py) without spinning up HTTP.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.email import EmailSender
from app.auth.models import ActionToken, ActionTokenPurpose, RefreshToken, User, UserRole
from app.config import settings


class AuthError(Exception):
    """Base for all auth-flow errors; routes.py maps these to HTTP status codes."""


class EmailAlreadyRegistered(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class TwoFactorRequired(AuthError):
    pass


class InvalidTwoFactorCode(AuthError):
    pass


class InvalidOrExpiredToken(AuthError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _expires_check(stored_dt: datetime) -> bool:
    """Return True if `stored_dt` is in the past.

    SQLite stores DateTime columns as naive strings (no tzinfo), while
    PostgreSQL preserves the UTC offset. We normalise by comparing both
    sides as UTC-naive, which is safe because every expires_at in this
    codebase is set via _utcnow() (always UTC) before being stored.
    PostgreSQL with tz-aware columns returns aware datetimes, so we strip
    the offset there too — the comparison result is identical either way.
    """
    now = _utcnow().replace(tzinfo=None)
    stored = stored_dt.replace(tzinfo=None) if stored_dt.tzinfo is not None else stored_dt
    return stored < now


# ---------------------------------------------------------------------------
# Registration + email verification
# ---------------------------------------------------------------------------

def register_user(db: Session, name: str, email: str, password: str, email_sender: EmailSender) -> User:
    existing = db.scalar(select(User).where(User.email == email.lower()))
    if existing:
        raise EmailAlreadyRegistered(f"{email} is already registered.")

    user = User(name=name, email=email.lower(), password_hash=security.hash_password(password),
                role=UserRole.USER)
    db.add(user)
    db.commit()
    db.refresh(user)

    send_verification_email(db, user, email_sender)
    return user


def send_verification_email(db: Session, user: User, email_sender: EmailSender) -> None:
    raw, hashed = security.generate_opaque_token()
    db.add(ActionToken(user_id=user.id, token_hash=hashed, purpose=ActionTokenPurpose.EMAIL_VERIFY,
                        expires_at=_utcnow() + security.EMAIL_VERIFY_TTL))
    db.commit()
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw}"
    email_sender.send(user.email, "Verify your VM ALGO account",
                       f"Hi {user.name},\n\nVerify your email: {link}\n\nExpires in 24 hours.")


def verify_email(db: Session, raw_token: str) -> User:
    token = _consume_action_token(db, raw_token, ActionTokenPurpose.EMAIL_VERIFY)
    user = db.get(User, token.user_id)
    user.is_email_verified = True
    db.commit()
    db.refresh(user)
    return user


def _consume_action_token(db: Session, raw_token: str, purpose: ActionTokenPurpose) -> ActionToken:
    token_hash = security.hash_for_lookup(raw_token)
    token = db.scalar(select(ActionToken).where(ActionToken.token_hash == token_hash, ActionToken.purpose == purpose))
    if token is None or token.used or _expires_check(token.expires_at):
        raise InvalidOrExpiredToken("This link is invalid or has expired.")
    token.used = True
    db.commit()
    return token


# ---------------------------------------------------------------------------
# Login + token pair issuance
# ---------------------------------------------------------------------------

def authenticate_user(db: Session, email: str, password: str, totp_code: str | None) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not security.verify_password(password, user.password_hash):
        raise InvalidCredentials("Incorrect email or password.")

    if user.is_2fa_enabled:
        if not totp_code:
            raise TwoFactorRequired("2FA code required.")
        if not pyotp.TOTP(user.totp_secret).verify(totp_code, valid_window=1):
            raise InvalidTwoFactorCode("Incorrect 2FA code.")

    return user


@dataclass
class TokenPair:
    access_token: str
    refresh_token_raw: str
    refresh_expires_at: datetime


def issue_token_pair(db: Session, user: User) -> TokenPair:
    access = security.create_access_token(user.id, user.role.value)
    raw, hashed = security.generate_opaque_token()
    expires_at = _utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=expires_at))
    db.commit()
    return TokenPair(access_token=access, refresh_token_raw=raw, refresh_expires_at=expires_at)


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> tuple[User, TokenPair]:
    """Validates + revokes the presented refresh token and issues a fresh
    pair (refresh token rotation — reusing an old, already-rotated refresh
    token is a sign of theft, which is why it's revoked immediately on use,
    not just on expiry)."""
    token_hash = security.hash_for_lookup(raw_refresh_token)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if token is None or token.revoked or _expires_check(token.expires_at):
        raise InvalidOrExpiredToken("Refresh token is invalid, expired, or already used.")

    token.revoked = True
    db.commit()

    user = db.get(User, token.user_id)
    return user, issue_token_pair(db, user)


def revoke_refresh_token(db: Session, raw_refresh_token: str) -> None:
    token_hash = security.hash_for_lookup(raw_refresh_token)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if token is not None:
        token.revoked = True
        db.commit()


def revoke_all_refresh_tokens(db: Session, user: User) -> None:
    for token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)):  # noqa: E712
        token.revoked = True
    db.commit()


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def request_password_reset(db: Session, email: str, email_sender: EmailSender) -> None:
    """Always succeeds from the caller's point of view, whether or not the
    email exists — prevents user enumeration via response timing/content."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        return
    raw, hashed = security.generate_opaque_token()
    db.add(ActionToken(user_id=user.id, token_hash=hashed, purpose=ActionTokenPurpose.PASSWORD_RESET,
                        expires_at=_utcnow() + security.PASSWORD_RESET_TTL))
    db.commit()
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw}"
    email_sender.send(user.email, "Reset your VM ALGO password",
                       f"Hi {user.name},\n\nReset your password: {link}\n\nExpires in 1 hour. "
                       f"If you didn't request this, ignore this email.")


def reset_password(db: Session, raw_token: str, new_password: str) -> User:
    token = _consume_action_token(db, raw_token, ActionTokenPurpose.PASSWORD_RESET)
    user = db.get(User, token.user_id)
    user.password_hash = security.hash_password(new_password)
    db.commit()
    revoke_all_refresh_tokens(db, user)  # force re-login everywhere after a reset
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# TOTP 2FA
# ---------------------------------------------------------------------------

def setup_2fa(db: Session, user: User) -> tuple[str, str, str]:
    """Returns (secret, otpauth_url, qr_code_png_base64). The secret is
    stored server-side as `pending_totp_secret` — NOT yet activated as
    `totp_secret` — until confirm_2fa() proves the user can generate a
    valid code with it. Client only ever needs to send back the 6-digit
    code, never the secret itself."""
    secret = pyotp.random_base32()
    otpauth_url = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="VM ALGO")

    img = qrcode.make(otpauth_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    user.pending_totp_secret = secret
    db.commit()

    return secret, otpauth_url, qr_b64


def confirm_2fa(db: Session, user: User, code: str) -> User:
    if not user.pending_totp_secret:
        raise InvalidOrExpiredToken("No pending 2FA setup — call setup_2fa first.")
    if not pyotp.TOTP(user.pending_totp_secret).verify(code, valid_window=1):
        raise InvalidTwoFactorCode("Incorrect 2FA code — setup not confirmed.")
    user.totp_secret = user.pending_totp_secret
    user.pending_totp_secret = None
    user.is_2fa_enabled = True
    db.commit()
    db.refresh(user)
    return user


def disable_2fa(db: Session, user: User, password: str) -> User:
    if not security.verify_password(password, user.password_hash):
        raise InvalidCredentials("Incorrect password.")
    user.is_2fa_enabled = False
    user.totp_secret = None
    db.commit()
    db.refresh(user)
    return user
