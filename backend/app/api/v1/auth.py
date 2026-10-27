from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app import schemas
from app.auth.deps import CSRF_COOKIE, SESSION_COOKIE, current_session, current_user, rate_limit
from app.db import get_db
from app.models import SessionRow, User
from app.services import accounts, org
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _dev(token: str | None) -> schemas.DevToken:
    return schemas.DevToken(dev_token=token if get_settings().dev_expose_tokens else None)


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    age = s.session_days * 86400
    response.set_cookie(SESSION_COOKIE, token, max_age=age, httponly=True, secure=s.cookie_secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=age, httponly=False, secure=s.cookie_secure, samesite="lax", path="/")


@router.post("/register", status_code=201, response_model=schemas.DevToken, dependencies=[rate_limit("register", 10, 3600)])
def register(body: schemas.RegisterIn, db: Session = Depends(get_db)):
    _, token = accounts.register(db, body.name, body.email, body.password, body.department_id)
    return _dev(token)


@router.post("/verify-email")
def verify_email(body: schemas.TokenIn, db: Session = Depends(get_db)):
    accounts.verify_email(db, body.token)
    return {"ok": True}


@router.post("/verify-email/resend", response_model=schemas.DevToken, dependencies=[rate_limit("resend", 5, 3600)])
def resend(body: schemas.EmailIn, db: Session = Depends(get_db)):
    return _dev(accounts.resend_verification(db, body.email))


@router.post("/login", dependencies=[rate_limit("login", 10, 300)])
def login(body: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    row, token = accounts.login(db, body.email, body.password)
    _set_cookies(response, token, row.csrf_token)
    return {**org.me(db, row.user), "csrf_token": row.csrf_token}


@router.post("/logout")
def logout(response: Response, row: SessionRow = Depends(current_session), db: Session = Depends(get_db)):
    accounts.logout(db, row)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(row: SessionRow = Depends(current_session), db: Session = Depends(get_db)):
    return {**org.me(db, row.user), "csrf_token": row.csrf_token}


@router.post("/password-reset/request", response_model=schemas.DevToken, dependencies=[rate_limit("reset", 5, 3600)])
def reset_request(body: schemas.EmailIn, db: Session = Depends(get_db)):
    return _dev(accounts.request_password_reset(db, body.email))


@router.post("/password-reset/confirm", dependencies=[rate_limit("reset-confirm", 10, 3600)])
def reset_confirm(body: schemas.ResetConfirmIn, db: Session = Depends(get_db)):
    accounts.confirm_password_reset(db, body.token, body.password)
    return {"ok": True}


@router.post("/resend-mine", response_model=schemas.DevToken)
def resend_mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _dev(accounts.resend_verification(db, user.email))
