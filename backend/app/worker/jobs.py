"""Background jobs (spec 13). Every job is idempotent: running it twice, or in two workers, does no harm.
Each job also takes a Postgres advisory lock so duplicate workers don't even overlap."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.db import session_factory
from app.models import Booking, Notification, User
from app.services import access, accounts, mailer, series, waitlist
from app.services.bookings import fmt, utcnow
from app.services.events import notify
from app.settings import get_settings

log = logging.getLogger("relay.worker")
MAX_EMAIL_ATTEMPTS = 6


def send_emails(db: Session, now: datetime | None = None, sender: Callable = mailer.send) -> int:
    now = now or utcnow()
    rows = db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(Notification.emailed_at.is_(None), Notification.email_attempts < MAX_EMAIL_ATTEMPTS)
        .order_by(Notification.created_at)
        .limit(100)
        .with_for_update(of=Notification, skip_locked=True)
    ).all()
    sent = 0
    for n, user in rows:
        # Exponential backoff: 1, 2, 4, 8, 16 minutes after each failure.
        if n.email_attempts and n.created_at + timedelta(minutes=2 ** (n.email_attempts - 1)) > now:
            continue
        try:
            sender(user.email, user.name, n.payload)
            n.emailed_at = now
            sent += 1
        except Exception as e:  # noqa: BLE001 - any SMTP failure is retried
            n.email_attempts += 1
            n.last_email_error = f"{type(e).__name__}: {e}"[:500]
            log.warning("email failed", extra={"extra_fields": {"notification": n.id, "attempt": n.email_attempts}})
        db.commit()
    return sent


def send_reminders(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    horizon = now + timedelta(minutes=get_settings().reminder_minutes_before)
    due = db.scalars(
        select(Booking)
        .where(
            Booking.status == "confirmed",
            Booking.kind != "maintenance",
            Booking.reminded_at.is_(None),
            func.lower(Booking.during) > now,
            func.lower(Booking.during) <= horizon,
        )
        .with_for_update(of=Booking, skip_locked=True)
    ).all()
    for b in due:
        b.reminded_at = now
        notify(
            db,
            b.user_id,
            "booking_reminder",
            title=f"Reminder: {b.resource.name} at {fmt(b.start)}",
            body=f"{b.resource.location or b.resource.lab.name}. Cancel in Relay if you no longer need it.",
            link="/bookings",
            booking_id=b.id,
        )
    db.commit()
    return len(due)


def complete_past_bookings(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    res = db.execute(
        update(Booking).where(Booking.status == "confirmed", func.upper(Booking.during) <= now).values(status="completed")
    )
    db.commit()
    return res.rowcount or 0


JOBS: dict[str, tuple[Callable[[Session], int | None], int]] = {
    # name: (function, interval seconds)
    "send_emails": (send_emails, 30),
    "expire_waitlist_offers": (waitlist.expire_offers, 60),
    "send_reminders": (send_reminders, 300),
    "complete_past_bookings": (complete_past_bookings, 600),
    "expire_access_requests": (access.expire_stale_requests, 3600),
    "warn_expiring_grants": (access.warn_expiring_grants, 3600),
    "extend_series": (series.extend_all, 6 * 3600),
    "expire_sessions": (accounts.expire_sessions, 24 * 3600),
}


def run(name: str) -> None:
    fn, _ = JOBS[name]
    lock_id = 0x52454C00 + list(JOBS).index(name)  # "REL" + index
    with session_factory()() as db:
        if not db.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id}):
            return
        try:
            result = fn(db)
            if result:
                log.info("job done", extra={"extra_fields": {"job": name, "result": result}})
        except Exception:
            db.rollback()
            log.exception("job failed", extra={"extra_fields": {"job": name}})
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id})
            db.commit()
