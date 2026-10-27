"""Request authentication: session cookie + double-submit CSRF header on unsafe methods."""

import hmac
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_token, limiter
from app.db import get_db
from app.errors import Forbidden, RateLimited, Unauthenticated
from app.models import SessionRow, User
from app.settings import get_settings

SESSION_COOKIE = "relay_session"
CSRF_COOKIE = "relay_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _load_session(request: Request, db: Session) -> SessionRow | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    if not row.user.is_active:
        return None
    return row


def current_session(request: Request, db: Session = Depends(get_db)) -> SessionRow:
    row = _load_session(request, db)
    if row is None:
        raise Unauthenticated("Please sign in.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, row.csrf_token):
            raise Forbidden("Missing or invalid CSRF token.", code="csrf_failed")
    return row


def current_user(row: SessionRow = Depends(current_session)) -> User:
    return row.user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    row = _load_session(request, db)
    return row.user if row else None


def rate_limit(name: str, limit: int, window_s: int):
    def dep(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        if not limiter.hit(f"{name}:{ip}", limit, window_s):
            raise RateLimited("Too many attempts. Please wait a few minutes and try again.")

    return Depends(dep)
