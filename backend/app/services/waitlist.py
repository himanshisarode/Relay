"""Waitlist (spec 7). An offer is a real booking with status 'held', created in the same transaction as the
cancellation that freed the slot, so the exclusion constraint keeps everyone else out until it's accepted."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, Conflict, Forbidden, NotFound
from app.models import Booking, User, WaitlistEntry
from app.services import bookings as bk
from app.services import permissions, rules
from app.services.events import audit, notify
from app.settings import get_settings


def join(db: Session, user: User, resource_id: int, start: datetime, end: datetime) -> WaitlistEntry:
    resource = bk.get_resource(db, resource_id)
    decision = permissions.require_book(db, user, resource)
    rules.validate(rules.Rules.of(resource), start, end, bk.utcnow(), get_settings().tz, privileged=decision.privileged)
    if not bk.busy(db, resource.id, start, end):
        raise Conflict("That time is free — book it directly.", code="slot_available")
    dup = db.scalar(
        select(WaitlistEntry.id).where(
            WaitlistEntry.user_id == user.id,
            WaitlistEntry.resource_id == resource.id,
            WaitlistEntry.status.in_(("waiting", "offered")),
            WaitlistEntry.desired_during.op("&&")(bk._span(start, end)),
        )
    )
    if dup:
        raise Conflict("You are already on the waitlist for an overlapping time.", code="already_waitlisted")
    entry = WaitlistEntry(resource_id=resource.id, user_id=user.id, desired_during=bk._span(start, end))
    db.add(entry)
    db.flush()
    audit(db, user.id, "waitlist.join", "waitlist_entry", entry.id, resource_id=resource.id, start=start, end=end)
    db.commit()
    return entry


def on_slot_freed(db: Session, freed: Booking, *, now: datetime) -> WaitlistEntry | None:
    """Offer the freed time to the earliest eligible waiting entry whose whole range is now free."""
    if freed.kind == "maintenance" or freed.end <= now:
        return None
    candidates = db.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.resource_id == freed.resource_id,
            WaitlistEntry.status == "waiting",
            WaitlistEntry.desired_during.op("&&")(freed.during),
            func.lower(WaitlistEntry.desired_during) > now,
        )
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
        .with_for_update(skip_locked=True)
    ).all()
    minutes = get_settings().waitlist_offer_minutes
    for entry in candidates:
        user = db.get(User, entry.user_id)
        start, end = entry.desired_during.lower, entry.desired_during.upper
        # Eligibility is re-checked at offer time (permission, quota).
        decision = permissions.can_book(db, user, freed.resource)
        if not decision.allowed:
            continue
        if not decision.privileged:
            try:
                bk.check_quota(db, user, freed.resource, start, end)
            except ApiError:
                continue
        hold = Booking(
            resource_id=freed.resource_id,
            user_id=user.id,
            grant_id=decision.grant_id,
            waitlist_entry_id=entry.id,
            kind=freed.kind,
            during=entry.desired_during,
            status="held",
        )
        try:
            with db.begin_nested():
                db.add(hold)
                db.flush()
        except IntegrityError:
            continue  # the rest of their range is still taken; try the next person
        entry.status = "offered"
        entry.offer_expires_at = now + timedelta(minutes=minutes)
        audit(db, None, "waitlist.offer", "waitlist_entry", entry.id, booking_id=hold.id)
        notify(
            db,
            user.id,
            "waitlist_offer",
            title=f"A slot on {freed.resource.name} is free for you",
            body=f"{bk.fmt(start)} – {bk.fmt(end)}. Confirm within {minutes} minutes or it passes to the next person.",
            link="/bookings",
            entry_id=entry.id,
            booking_id=hold.id,
        )
        return entry
    return None


def _held_booking(db: Session, entry: WaitlistEntry) -> Booking | None:
    return db.scalar(select(Booking).where(Booking.waitlist_entry_id == entry.id, Booking.status == "held"))


def _get_own(db: Session, user: User, entry_id: int) -> WaitlistEntry:
    e = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id).with_for_update())
    if e is None or e.user_id != user.id:
        raise NotFound("Waitlist entry not found.")
    return e


def accept(db: Session, user: User, entry_id: int) -> Booking:
    e = _get_own(db, user, entry_id)
    now = bk.utcnow()
    if e.status != "offered" or (e.offer_expires_at and e.offer_expires_at <= now):
        raise Conflict("This offer is no longer available.", code="offer_expired")
    hold = _held_booking(db, e)
    if hold is None:
        raise Conflict("This offer is no longer available.", code="offer_expired")
    if not permissions.can_book(db, user, hold.resource).allowed:
        raise Forbidden("You no longer have access to this resource.")
    hold.status = "confirmed"
    e.status = "fulfilled"
    audit(db, user.id, "waitlist.accept", "waitlist_entry", e.id, booking_id=hold.id)
    db.commit()
    return hold


def leave(db: Session, user: User, entry_id: int) -> None:
    e = _get_own(db, user, entry_id)
    if e.status not in ("waiting", "offered"):
        return
    _release(db, e, "cancelled", actor_id=user.id)
    db.commit()


def _release(db: Session, e: WaitlistEntry, status: str, actor_id: int | None) -> None:
    now = bk.utcnow()
    hold = _held_booking(db, e) if e.status == "offered" else None
    e.status = status
    audit(db, actor_id, f"waitlist.{status}", "waitlist_entry", e.id)
    if hold is not None:
        hold.status = "cancelled"
        hold.cancelled_at = now
        hold.cancel_reason = "waitlist offer released"
        db.flush()
        on_slot_freed(db, hold, now=now)


def expire_offers(db: Session, now: datetime | None = None) -> int:
    """Worker job: lapsed offers pass to the next entry. Idempotent."""
    now = now or bk.utcnow()
    lapsed = db.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.status == "offered", WaitlistEntry.offer_expires_at <= now)
        .with_for_update(skip_locked=True)
    ).all()
    for e in lapsed:
        _release(db, e, "expired", actor_id=None)
        notify(db, e.user_id, "waitlist_expired", title="Your waitlist offer expired", email=False)
    # Entries whose time has passed are no longer useful.
    db.execute(
        WaitlistEntry.__table__.update()
        .where(WaitlistEntry.status == "waiting", func.upper(WaitlistEntry.desired_during) <= now)
        .values(status="expired")
    )
    db.commit()
    return len(lapsed)


def mine(db: Session, user: User) -> list[WaitlistEntry]:
    return list(
        db.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.user_id == user.id, WaitlistEntry.status.in_(("waiting", "offered")))
            .order_by(func.lower(WaitlistEntry.desired_during))
        )
    )
