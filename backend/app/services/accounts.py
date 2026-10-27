"""Registration, email verification, sessions and password reset (plan Q1: email + password)."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import hash_password, hash_token, new_token, verify_password
from app.errors import ApiError, Conflict, NotFound, Unauthenticated
from app.models import AuthToken, Department, DepartmentMember, SessionRow, User
from app.services.bookings import utcnow
from app.services.events import audit, notify
from app.settings import get_settings

TOKEN_TTL = {"verify_email": timedelta(hours=48), "password_reset": timedelta(hours=1)}


def _issue(db: Session, user: User, purpose: str) -> str:
    token = new_token()
    db.add(
        AuthToken(user_id=user.id, purpose=purpose, token_hash=hash_token(token), expires_at=utcnow() + TOKEN_TTL[purpose])
    )
    return token


def _consume(db: Session, token: str, purpose: str) -> User:
    row = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_token(token), AuthToken.purpose == purpose).with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise ApiError("This link is invalid or has expired.", code="invalid_token")
    row.used_at = utcnow()
    return db.get(User, row.user_id)


def send_verification(db: Session, user: User) -> str:
    token = _issue(db, user, "verify_email")
    link = f"{get_settings().base_url}/verify-email?token={token}"
    notify(
        db,
        user.id,
        "email_verification",
        title="Confirm your email for Relay",
        body="Open this link to confirm your address. It is valid for 48 hours.",
        link=link,
    )
    return token


def register(db: Session, name: str, email: str, password: str, department_id: int | None) -> tuple[User, str]:
    if department_id is not None and db.get(Department, department_id) is None:
        raise NotFound("Department not found.")
    user = User(name=name.strip(), email=email.strip().lower(), password_hash=hash_password(password))
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError:
        raise Conflict(
            "An account with this email already exists. Try signing in or resetting your password.", code="email_taken"
        ) from None
    if department_id is not None:
        # Unverified until a department admin confirms it (spec 3.3).
        db.add(DepartmentMember(user_id=user.id, department_id=department_id, role="member", verified=False))
    token = send_verification(db, user)
    audit(db, user.id, "user.register", "user", user.id, department_id=department_id)
    db.commit()
    return user, token


def verify_email(db: Session, token: str) -> User:
    user = _consume(db, token, "verify_email")
    user.email_verified = True
    audit(db, user.id, "user.verify_email", "user", user.id)
    db.commit()
    return user


def resend_verification(db: Session, email: str) -> str | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.email_verified:
        return None
    token = send_verification(db, user)
    db.commit()
    return token


def login(db: Session, email: str, password: str) -> tuple[SessionRow, str]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not verify_password(user.password_hash if user else None, password) or user is None or not user.is_active:
        raise Unauthenticated("Email or password is incorrect.", code="bad_credentials")
    token = new_token()
    row = SessionRow(
        token_hash=hash_token(token),
        user_id=user.id,
        csrf_token=new_token(),
        expires_at=utcnow() + timedelta(days=get_settings().session_days),
    )
    db.add(row)
    audit(db, user.id, "user.login", "user", user.id)
    db.commit()
    db.refresh(row)
    return row, token


def logout(db: Session, row: SessionRow) -> None:
    row.revoked_at = utcnow()
    db.commit()


def request_password_reset(db: Session, email: str) -> str | None:
    """Always 'succeeds' from the caller's view so it can't be used to discover accounts."""
    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    if user is None:
        return None
    token = _issue(db, user, "password_reset")
    notify(
        db,
        user.id,
        "password_reset",
        title="Reset your Relay password",
        body="Open this link within an hour to choose a new password. Ignore this email if you didn't ask.",
        link=f"{get_settings().base_url}/reset-password?token={token}",
    )
    db.commit()
    return token


def confirm_password_reset(db: Session, token: str, password: str) -> None:
    user = _consume(db, token, "password_reset")
    user.password_hash = hash_password(password)
    user.email_verified = True  # they proved control of the inbox
    db.execute(
        update(SessionRow).where(SessionRow.user_id == user.id, SessionRow.revoked_at.is_(None)).values(revoked_at=utcnow())
    )
    audit(db, user.id, "user.password_reset", "user", user.id)
    db.commit()


def expire_sessions(db: Session, now: datetime | None = None) -> None:
    db.execute(SessionRow.__table__.delete().where(SessionRow.expires_at < (now or utcnow()) - timedelta(days=30)))
    db.commit()
