"""
VM ALGO — Auth routes
=========================
Access token: returned in the JSON body (for an Authorization-header client)
AND set as an HttpOnly cookie (for a browser client) — both point at the
same short-lived JWT, neither is more privileged than the other.
Refresh token: HttpOnly cookie ONLY, never in the JSON body. It's the
longer-lived, more sensitive credential; keeping it out of JS-readable
response bodies (and therefore out of `localStorage`, which the frontend
guidance elsewhere in this repo explicitly warns against for anything
sensitive) is the point of using a cookie for it at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, get_current_user
from app.auth.email import EmailSender, get_email_sender
from app.auth.models import User
from app.auth.schemas import (
    Confirm2FARequest, Disable2FARequest, ForgotPasswordRequest, LoginRequest, LoginResponse,
    RegisterRequest, ResendVerificationRequest, ResetPasswordRequest, Setup2FAResponse, UserPublic,
    VerifyEmailRequest,
)
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookies(response: Response, access_token: str, refresh_token_raw: str, refresh_max_age_seconds: int) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME, access_token, httponly=True, secure=settings.COOKIE_SECURE,
        samesite="lax", domain=settings.COOKIE_DOMAIN, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME, refresh_token_raw, httponly=True, secure=settings.COOKIE_SECURE,
        samesite="lax", domain=settings.COOKIE_DOMAIN, max_age=refresh_max_age_seconds, path="/api/auth",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(REFRESH_COOKIE_NAME, domain=settings.COOKIE_DOMAIN, path="/api/auth")


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db), sender: EmailSender = Depends(get_email_sender)):
    try:
        user = service.register_user(db, body.name, body.email, body.password, sender)
    except service.EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return user


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user = service.authenticate_user(db, body.email, body.password, body.totp_code)
    except service.TwoFactorRequired:
        return LoginResponse(requires_2fa=True)
    except (service.InvalidCredentials, service.InvalidTwoFactorCode) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    pair = service.issue_token_pair(db, user)
    _set_auth_cookies(response, pair.access_token, pair.refresh_token_raw,
                       settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    return LoginResponse(requires_2fa=False, access_token=pair.access_token, user=UserPublic.model_validate(user))


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token cookie present.")
    try:
        user, pair = service.rotate_refresh_token(db, refresh_token)
    except service.InvalidOrExpiredToken as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    _set_auth_cookies(response, pair.access_token, pair.refresh_token_raw,
                       settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    return LoginResponse(requires_2fa=False, access_token=pair.access_token, user=UserPublic.model_validate(user))


@router.post("/logout")
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    if refresh_token:
        service.revoke_refresh_token(db, refresh_token)
    _clear_auth_cookies(response)
    return {"detail": "Logged out."}


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
def request_email_verification(body: ResendVerificationRequest, db: Session = Depends(get_db),
                                 sender: EmailSender = Depends(get_email_sender)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and not user.is_email_verified:
        service.send_verification_email(db, user, sender)
    return {"detail": "If that email exists and is unverified, a verification link has been sent."}


@router.post("/verify-email/confirm", response_model=UserPublic)
def confirm_email_verification(body: VerifyEmailRequest, db: Session = Depends(get_db)):
    try:
        return service.verify_email(db, body.token)
    except service.InvalidOrExpiredToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db),
                     sender: EmailSender = Depends(get_email_sender)):
    service.request_password_reset(db, body.email, sender)
    return {"detail": "If that email exists, a password reset link has been sent."}


@router.post("/reset-password", response_model=UserPublic)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        return service.reset_password(db, body.token, body.new_password)
    except service.InvalidOrExpiredToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/2fa/setup", response_model=Setup2FAResponse)
def setup_2fa(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret, otpauth_url, qr_b64 = service.setup_2fa(db, user)
    return Setup2FAResponse(secret=secret, otpauth_url=otpauth_url, qr_code_png_base64=qr_b64)


@router.post("/2fa/confirm", response_model=UserPublic)
def confirm_2fa(body: Confirm2FARequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return service.confirm_2fa(db, user, body.code)
    except (service.InvalidTwoFactorCode, service.InvalidOrExpiredToken) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/2fa/disable", response_model=UserPublic)
def disable_2fa(body: Disable2FARequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return service.disable_2fa(db, user, body.password)
    except service.InvalidCredentials as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
