"""
VM ALGO — Auth security primitives
======================================
- Passwords: bcrypt, used directly (NOT via passlib — passlib is
  unmaintained since 2020 and its bundled bcrypt self-test breaks against
  bcrypt>=4.1's stricter 72-byte enforcement; that's not a hypothetical,
  it's what this module hit during testing before this rewrite). Bcrypt's
  72-BYTE limit (not 72 characters — UTF-8 multi-byte input hits the cap
  sooner) is enforced explicitly in RegisterRequest/ResetPasswordRequest
  validators in schemas.py, so it's a clean 422 at the API boundary
  instead of a 500 from inside the hashing call.
- Access tokens: short-lived JWT (default 15 min), signed with JWT_SECRET_KEY
  from settings (never hardcoded — see app/config.py).
- Refresh tokens: NOT JWTs. An opaque random string is handed to the client;
  only its SHA-256 hash is stored server-side (in RefreshToken.token_hash).
  This makes refresh tokens revocable (delete/flag the DB row) — a stateless
  JWT refresh token can't be revoked before it expires without an extra
  blocklist anyway, so an opaque+hashed token is simpler AND more secure.
- Action tokens (email verify / password reset): same opaque+hashed pattern,
  single-use (`used` flag) and short-lived (see ACTION_TOKEN_TTL below).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

EMAIL_VERIFY_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)

MAX_PASSWORD_BYTES = 72  # bcrypt's hard limit — see module docstring


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_opaque_token() -> tuple[str, str]:
    """Returns (raw_token_for_client, sha256_hash_for_storage)."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_token(raw)


def hash_for_lookup(raw_token: str) -> str:
    """Hash an incoming raw token the same way, to look it up by its hash."""
    return _hash_token(raw_token)


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/tampered token."""
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token.")
    return payload
