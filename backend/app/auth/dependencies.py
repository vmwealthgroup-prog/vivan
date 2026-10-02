from __future__ import annotations

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import security
from app.auth.models import User, UserRole
from app.db import get_db

ACCESS_COOKIE_NAME = "vmalgo_access_token"
REFRESH_COOKIE_NAME = "vmalgo_refresh_token"


def get_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    if not access_token:
        raise unauthorized
    try:
        payload = security.decode_access_token(access_token)
    except jwt.PyJWTError:
        raise unauthorized
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise unauthorized
    return user


def require_role(*allowed_roles: UserRole):
    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return user
    return _dependency


require_admin = require_role(UserRole.ADMIN)
