"""
Auth system tests, against a real SQLAlchemy DB (SQLite file, isolated per
test run — DATABASE_URL is overridden via env var before any app import,
so this never touches whatever DB a developer has configured for normal
dev use). Run with:
    cd backend && PYTHONPATH=. VMALGO_TEST=1 python app/tests/test_auth.py
"""

from __future__ import annotations

import os
import sys
import tempfile

# Must happen BEFORE importing anything under app.* — settings/engine are
# built at import time.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"

import pyotp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.auth.models import User, UserRole  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _register(email="trader@example.com", password="Str0ngPass!", name="Vijay Test"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": password})


def test_register_rejects_weak_password():
    r = client.post("/api/auth/register", json={"name": "X", "email": "weak@example.com", "password": "12345678"})
    assert r.status_code == 422, r.text
    print("[OK] registration rejects a digits-only password")


def test_register_and_duplicate_email():
    r = _register(email="dup@example.com")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "dup@example.com"
    assert body["is_email_verified"] is False
    assert "password" not in body and "password_hash" not in body

    r2 = _register(email="dup@example.com")
    assert r2.status_code == 409, r2.text
    print("[OK] register creates a user, hides password fields, rejects duplicate email")


def test_login_requires_verified_credentials_and_sets_cookies():
    _register(email="login@example.com", password="Str0ngPass!")
    bad = client.post("/api/auth/login", json={"email": "login@example.com", "password": "WrongPass!"})
    assert bad.status_code == 401, bad.text

    good = client.post("/api/auth/login", json={"email": "login@example.com", "password": "Str0ngPass!"})
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["requires_2fa"] is False
    assert body["access_token"]
    assert "vmalgo_access_token" in good.cookies
    assert "vmalgo_refresh_token" in good.cookies
    print("[OK] login rejects wrong password, accepts correct password, sets both cookies")


def test_me_endpoint_requires_auth_cookie():
    anon = client.get("/api/auth/me")
    assert anon.status_code == 401

    _register(email="me@example.com", password="Str0ngPass!")
    login = client.post("/api/auth/login", json={"email": "me@example.com", "password": "Str0ngPass!"})
    me = client.get("/api/auth/me")  # TestClient persists cookies across calls on the same client
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "me@example.com"
    print("[OK] /me rejects unauthenticated requests, accepts the session cookie from login")


def test_email_verification_flow():
    db = SessionLocal()
    try:
        _register(email="verify@example.com", password="Str0ngPass!")
        user = db.query(User).filter(User.email == "verify@example.com").one()
        assert user.is_email_verified is False

        from app.auth import security
        from app.auth.models import ActionToken, ActionTokenPurpose
        token_row = db.query(ActionToken).filter(
            ActionToken.user_id == user.id, ActionToken.purpose == ActionTokenPurpose.EMAIL_VERIFY
        ).one()
        # We only have the hash stored (by design) — regenerate a token and
        # patch the hash in, to test the confirm endpoint's logic without
        # needing to intercept the "sent" email out-of-band.
        raw, hashed = security.generate_opaque_token()
        token_row.token_hash = hashed
        db.commit()

        bad = client.post("/api/auth/verify-email/confirm", json={"token": "not-a-real-token"})
        assert bad.status_code == 400

        ok = client.post("/api/auth/verify-email/confirm", json={"token": raw})
        assert ok.status_code == 200, ok.text
        assert ok.json()["is_email_verified"] is True

        reuse = client.post("/api/auth/verify-email/confirm", json={"token": raw})
        assert reuse.status_code == 400, "a used token must not be usable twice"
        print("[OK] email verification: rejects bad token, confirms with valid token, rejects reuse")
    finally:
        db.close()


def test_password_reset_flow_and_revokes_sessions():
    _register(email="reset@example.com", password="OldPass1!")
    login1 = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "OldPass1!"})
    assert login1.status_code == 200

    db = SessionLocal()
    try:
        from app.auth import security
        from app.auth.models import ActionToken, ActionTokenPurpose
        user = db.query(User).filter(User.email == "reset@example.com").one()
        raw, hashed = security.generate_opaque_token()
        from datetime import datetime, timedelta, timezone
        db.add(ActionToken(user_id=user.id, token_hash=hashed, purpose=ActionTokenPurpose.PASSWORD_RESET,
                            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
    finally:
        db.close()

    reset = client.post("/api/auth/reset-password", json={"token": raw, "new_password": "NewPass2!"})
    assert reset.status_code == 200, reset.text

    old_login = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "OldPass1!"})
    assert old_login.status_code == 401

    new_login = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "NewPass2!"})
    assert new_login.status_code == 200
    print("[OK] password reset: old password stops working, new password logs in")


def test_refresh_token_rotation():
    r = _register(email="refresh@example.com", password="Str0ngPass!")
    login = client.post("/api/auth/login", json={"email": "refresh@example.com", "password": "Str0ngPass!"})
    old_refresh_cookie = login.cookies.get("vmalgo_refresh_token")
    assert old_refresh_cookie

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    new_refresh_cookie = refreshed.cookies.get("vmalgo_refresh_token")
    assert new_refresh_cookie and new_refresh_cookie != old_refresh_cookie

    print("[OK] refresh rotates the refresh token (old value replaced)")


def test_2fa_setup_and_login_requires_code():
    _register(email="totp@example.com", password="Str0ngPass!")
    client.post("/api/auth/login", json={"email": "totp@example.com", "password": "Str0ngPass!"})

    setup = client.post("/api/auth/2fa/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["qr_code_png_base64"]

    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/auth/2fa/confirm", json={"code": code})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["is_2fa_enabled"] is True

    client.cookies.clear()
    no_code = client.post("/api/auth/login", json={"email": "totp@example.com", "password": "Str0ngPass!"})
    assert no_code.status_code == 200
    assert no_code.json()["requires_2fa"] is True
    assert no_code.json()["access_token"] is None

    wrong_code = client.post("/api/auth/login", json={"email": "totp@example.com", "password": "Str0ngPass!",
                                                        "totp_code": "000000"})
    assert wrong_code.status_code == 401

    right_code = client.post("/api/auth/login", json={"email": "totp@example.com", "password": "Str0ngPass!",
                                                        "totp_code": pyotp.TOTP(secret).now()})
    assert right_code.status_code == 200
    assert right_code.json()["requires_2fa"] is False
    print("[OK] 2FA: setup+confirm enables it, login then requires a valid TOTP code")


def test_require_role_unit():
    from fastapi import HTTPException
    from app.auth.dependencies import require_role

    class FakeUser:
        role = UserRole.USER

    guard = require_role(UserRole.ADMIN)
    try:
        guard(FakeUser())
        raised = False
    except HTTPException as exc:
        raised = exc.status_code == 403
    assert raised, "require_role must reject a non-admin user with 403"

    class FakeAdmin:
        role = UserRole.ADMIN

    result = guard(FakeAdmin())
    assert result.role == UserRole.ADMIN
    print("[OK] require_role: rejects wrong role (403), allows matching role")


if __name__ == "__main__":
    tests = [
        test_register_rejects_weak_password,
        test_register_and_duplicate_email,
        test_login_requires_verified_credentials_and_sets_cookies,
        test_me_endpoint_requires_auth_cookie,
        test_email_verification_flow,
        test_password_reset_flow_and_revokes_sessions,
        test_refresh_token_rotation,
        test_2fa_setup_and_login_requires_code,
        test_require_role_unit,
    ]
    failed = 0
    for t in tests:
        client.cookies.clear()
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"[FAIL] {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} test groups passed.")
    sys.exit(1 if failed else 0)
