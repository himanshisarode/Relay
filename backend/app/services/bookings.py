"""Booking lifecycle (spec 5). Permission -> rules -> quota -> insert; the exclusion constraint has the final say."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, Conflict, Forbidden, NotFound, QuotaExceeded, RuleViolation, SlotConflict
from app.models import AccessGrant, Booking, Lab, LabMember, Resource, User
from app.services import permissions, rules
from app.services.events import audit, notify
from app.settings import get_settings

ACTIVE = ("confirmed", "held")
EXCLUSION_VIOLATION = "23P01"


def utcnow() -> datetime:
    return datetime.now(UTC)


def fmt(dt: datetime) -> str:
    return dt.astimezone(get_settings().tz).strftime("%a %d %b %Y, %H:%M %Z")


def get_resource(db: Session, resource_id: int, *, lock: bool = False) -> Resource:
    stmt = select(Resource).where(Resource.id == resource_id)
    if lock:
        stmt = stmt.with_for_update(of=Resource)
    r = db.scalar(stmt)
    if r is None:
        raise NotFound("Resource not found.")
    return r


def get_booking(db: Session, booking_id: int, *, lock: bool = False) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id)
    if lock:
        stmt = stmt.with_for_update(of=Booking)
    b = db.scalar(stmt)
    if b is None:
        raise NotFound("Booking not found.")
    return b


def _span(start: datetime, end: datetime) -> Range[datetime]:
    return Range(start, end, bounds="[)")


# ---- quota ---------------------------------------------------------------------------------------------


def used_minutes(
    db: Session, user_id: int, resource_id: int, week_start_local: date, *, exclude_id: int | None = None
) -> int:
    tz = get_settings().tz
    ws = datetime.combine(week_start_local, datetime.min.time(), tz)
    week = _span(ws, datetime.combine(week_start_local + timedelta(days=7), datetime.min.time(), tz))
    overlap = func.coalesce(
        func.sum(func.extract("epoch", func.upper(Booking.during * week) - func.lower(Booking.during * week))), 0
    )
    stmt = select(overlap).where(
        Booking.user_id == user_id,
        Booking.resource_id == resource_id,
        Booking.kind == "usage",
        Booking.status.in_(ACTIVE),
        Booking.during.op("&&")(week),
    )
    if exclude_id is not None:
        stmt = stmt.where(Booking.id != exclude_id)
    return int(db.scalar(stmt) // 60)


def check_quota(db: Session, user: User, resource: Resource, start: datetime, end: datetime) -> None:
    quota = resource.weekly_quota_min
    if quota is None or resource.type == "meeting_room":
        return
    for week, minutes in rules.minutes_by_week(start, end, get_settings().tz).items():
        used = used_minutes(db, user.id, resource.id, week)
        if used + minutes > quota:
            remaining = max(0, quota - used)
            raise QuotaExceeded(
                f"This exceeds your weekly limit of {quota} minutes on this resource; "
                f"you have {remaining} minutes left for the week of {week:%d %b}.",
                weekly_quota_min=quota,
                used_min=used,
                remaining_min=remaining,
                week_start=week.isoformat(),
            )


# ---- availability ----------------------------------------------------------------------------------------


def busy(db: Session, resource_id: int, frm: datetime, to: datetime) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking)
            .where(Booking.resource_id == resource_id, Booking.status.in_(ACTIVE), Booking.during.op("&&")(_span(frm, to)))
            .order_by(func.lower(Booking.during))
        )
    )


def suggest_slots(db: Session, resource: Resource, minutes: int, after: datetime, n: int = 3) -> list[dict]:
    """Next free slots of the same length within the next 7 days (cheap: one query, linear scan)."""
    tz = get_settings().tz
    rl = rules.Rules.of(resource)
    horizon = after + timedelta(days=7)
    taken = [(b.start, b.end) for b in busy(db, resource.id, after, horizon + timedelta(minutes=minutes))]
    step = timedelta(minutes=rl.slot_granularity_min)
    length = timedelta(minutes=minutes)
    out: list[dict] = []
    day = after.astimezone(tz).date()
    while day <= horizon.astimezone(tz).date() and len(out) < n:
        for ws, we in rules.open_windows(rl, day, tz):
            s = ws
            while s + length <= we and len(out) < n:
                if s >= after and not any(s < te and ts < s + length for ts, te in taken):
                    out.append({"start": s.isoformat(), "end": (s + length).isoformat()})
                    s += length
                else:
                    s += step
        day += timedelta(days=1)
    return out


def booker_lab_names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(LabMember.user_id, func.min(Lab.name))
        .join(Lab, Lab.id == LabMember.lab_id)
        .where(LabMember.user_id.in_(user_ids))
        .group_by(LabMember.user_id)
    ).all()
    return {uid: name for uid, name in rows}


def availability(db: Session, viewer: User, resource: Resource, frm: datetime, to: datetime) -> list[dict]:
    """Calendar entries with privacy applied (spec 14 / plan Q3): everyone sees 'Booked' + the booker's lab;
    owners see their own details; the lab's professor and admins see who and why."""
    if to <= frm or to - frm > timedelta(days=62):
        raise RuleViolation("Pick a range of at most 62 days.", rule="range")
    facts = permissions.load_facts(db, viewer)
    manager = permissions.can_manage(facts, permissions.ResourceFacts.of(resource))
    items = busy(db, resource.id, frm, to)
    labs = booker_lab_names(db, {b.user_id for b in items})
    out = []
    for b in items:
        mine = b.user_id == viewer.id
        if b.kind == "maintenance":
            label = "Maintenance"
        elif mine:
            label = b.purpose or "Your booking"
        elif manager:
            label = b.user.name
        else:
            label = f"Booked · {labs[b.user_id]}" if b.user_id in labs else "Booked"
        out.append(
            {
                "id": b.id if (mine or manager) else None,
                "start": b.start,
                "end": b.end,
                "kind": b.kind,
                "status": b.status,
                "label": label,
                "mine": mine,
                "user_name": b.user.name if (mine or manager) else None,
                "purpose": b.purpose if (mine or manager) else None,
                "series_id": b.series_id if (mine or manager) else None,
            }
        )
    return out


# ---- create / cancel / reschedule -----------------------------------------------------------------------


def _lock_user_resource(db: Session, user_id: int, resource_id: int) -> None:
    """Serialize one user's bookings on one resource so two parallel requests can't both pass the quota."""
    db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": user_id % 2**31, "b": resource_id % 2**31})


def _insert(db: Session, booking: Booking, resource: Resource, minutes: int, start: datetime) -> Booking:
    try:
        with db.begin_nested():
            db.add(booking)
            db.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) != EXCLUSION_VIOLATION:
            raise
        raise SlotConflict(
            "That slot was just booked by someone else.",
            next_available=suggest_slots(db, resource, minutes, max(start, utcnow())),
        ) from None
    return booking


def create_booking_tx(
    db: Session,
    user: User,
    resource_id: int,
    start: datetime,
    end: datetime,
    purpose: str = "",
    *,
    now: datetime | None = None,
    series_id: int | None = None,
    skip_rules: bool = False,
) -> Booking:
    """Validate and insert without committing (callers own the transaction)."""
    now = now or utcnow()
    resource = get_resource(db, resource_id)
    decision = permissions.require_book(db, user, resource)
    if not skip_rules:
        rules.validate(rules.Rules.of(resource), start, end, now, get_settings().tz, privileged=decision.privileged)
    if decision.grant_id is not None:
        grant = db.get(AccessGrant, decision.grant_id)
        if end > grant.expires_at:
            raise RuleViolation(
                f"Your access ends {fmt(grant.expires_at)}; book within it.",
                rule="beyond_grant",
                grant_expires_at=grant.expires_at.isoformat(),
            )
    _lock_user_resource(db, user.id, resource.id)
    if not decision.privileged:
        check_quota(db, user, resource, start, end)
    booking = Booking(
        resource_id=resource.id,
        user_id=user.id,
        series_id=series_id,
        grant_id=decision.grant_id,
        kind="meeting" if resource.type == "meeting_room" else "usage",
        during=_span(start, end),
        status="confirmed",
        purpose=purpose.strip(),
    )
    _insert(db, booking, resource, int((end - start).total_seconds() // 60), start)
    audit(
        db, user.id, "booking.create", "booking", booking.id, resource_id=resource.id, start=start, end=end, via=decision.via
    )
    return booking


def create_booking(db: Session, user: User, resource_id: int, start: datetime, end: datetime, purpose: str = "") -> Booking:
    b = create_booking_tx(db, user, resource_id, start, end, purpose)
    db.commit()
    return b


def cancel_booking_tx(
    db: Session,
    actor: User,
    booking: Booking,
    reason: str | None,
    *,
    now: datetime | None = None,
    notify_owner: bool = True,
    system: bool = False,
) -> Booking:
    now = now or utcnow()
    if booking.status not in ACTIVE:
        raise Conflict("This booking is not active.", code="not_active")
    if booking.end <= now:
        raise Conflict("This booking has already ended.", code="already_ended")
    is_owner = booking.user_id == actor.id
    if not is_owner and not system:
        permissions.require_manage(db, actor, booking.resource)
        if not (reason and reason.strip()):
            raise RuleViolation("Give a reason when cancelling someone else's booking.", rule="reason_required")
    booking.status = "cancelled"
    booking.cancelled_at = now
    booking.cancelled_by = actor.id
    booking.cancel_reason = (reason or "").strip() or None
    late = rules.is_late_cancel(rules.Rules.of(booking.resource), booking.start, now)
    audit(db, actor.id, "booking.cancel", "booking", booking.id, reason=booking.cancel_reason, late=late, by_owner=is_owner)
    if notify_owner and not is_owner:
        notify(
            db,
            booking.user_id,
            "booking_cancelled",
            title=f"Your booking of {booking.resource.name} was cancelled",
            body=f"{fmt(booking.start)} – {fmt(booking.end)}. Reason: {booking.cancel_reason or 'not given'}.",
            link="/bookings",
            booking_id=booking.id,
        )
    db.flush()
    from app.services import waitlist  # local import: waitlist depends on bookings

    waitlist.on_slot_freed(db, booking, now=now)
    return booking


def cancel_booking(db: Session, actor: User, booking_id: int, reason: str | None) -> Booking:
    b = get_booking(db, booking_id, lock=True)
    _visible_or_404(db, actor, b)
    cancel_booking_tx(db, actor, b, reason)
    db.commit()
    return b


def reschedule(db: Session, actor: User, booking_id: int, start: datetime, end: datetime) -> Booking:
    """Atomic cancel-and-create (AC-B5): any failure rolls back both halves, leaving the original untouched."""
    old = get_booking(db, booking_id, lock=True)
    _visible_or_404(db, actor, old)
    if old.user_id != actor.id:
        raise Forbidden("Only the person who made a booking can reschedule it.")
    if old.series_id is not None:
        raise Conflict("Reschedule recurring meetings from the series instead.", code="series_occurrence")
    try:
        old.status = "cancelled"
        old.cancelled_at = utcnow()
        old.cancelled_by = actor.id
        old.cancel_reason = "rescheduled"
        db.flush()
        new = create_booking_tx(db, actor, old.resource_id, start, end, old.purpose)
        audit(db, actor.id, "booking.reschedule", "booking", new.id, from_booking=old.id)
        db.commit()
    except ApiError:
        db.rollback()
        raise
    return new


def create_maintenance(
    db: Session, actor: User, resource_id: int, start: datetime, end: datetime, reason: str, cancel_conflicts: bool
) -> tuple[Booking, list[Booking]]:
    resource = get_resource(db, resource_id)
    permissions.require_manage(db, actor, resource)
    if end <= start:
        raise RuleViolation("The block must end after it starts.", rule="end_before_start")
    clashes = [b for b in busy(db, resource.id, start, end) if b.kind != "maintenance"]
    if clashes and not cancel_conflicts:
        raise Conflict(
            f"{len(clashes)} booking(s) overlap this block. Confirm to cancel them and notify their owners.",
            code="maintenance_conflicts",
            bookings=[
                {"id": b.id, "user_name": b.user.name, "start": b.start.isoformat(), "end": b.end.isoformat()}
                for b in clashes
            ],
        )
    for b in clashes:
        b.status = "cancelled"
        b.cancelled_at = utcnow()
        b.cancelled_by = actor.id
        b.cancel_reason = f"Maintenance: {reason}"
        audit(db, actor.id, "booking.cancel", "booking", b.id, reason=b.cancel_reason, maintenance=True)
        notify(
            db,
            b.user_id,
            "booking_cancelled",
            title=f"Your booking of {resource.name} was cancelled",
            body=f"{fmt(b.start)} – {fmt(b.end)} overlaps scheduled maintenance ({reason}).",
            link="/bookings",
            booking_id=b.id,
        )
    db.flush()
    block = Booking(
        resource_id=resource.id,
        user_id=actor.id,
        kind="maintenance",
        during=_span(start, end),
        status="confirmed",
        purpose=reason.strip(),
    )
    _insert(db, block, resource, int((end - start).total_seconds() // 60), start)
    audit(
        db,
        actor.id,
        "maintenance.create",
        "booking",
        block.id,
        resource_id=resource.id,
        start=start,
        end=end,
        cancelled=[b.id for b in clashes],
    )
    db.commit()
    return block, clashes


def my_bookings(
    db: Session, user: User, frm: datetime | None, to: datetime | None, include_cancelled: bool
) -> list[Booking]:
    stmt = select(Booking).where(Booking.user_id == user.id, Booking.kind != "maintenance")
    if frm and to:
        stmt = stmt.where(Booking.during.op("&&")(_span(frm, to)))
    elif frm:
        stmt = stmt.where(func.upper(Booking.during) > frm)
    elif to:
        stmt = stmt.where(func.lower(Booking.during) < to)
    if not include_cancelled:
        stmt = stmt.where(Booking.status != "cancelled")
    return list(db.scalars(stmt.order_by(func.lower(Booking.during))))


def _visible_or_404(db: Session, actor: User, b: Booking) -> None:
    """Don't reveal that someone else's booking exists unless the actor manages the resource."""
    if b.user_id == actor.id:
        return
    facts = permissions.load_facts(db, actor)
    if not permissions.can_manage(facts, permissions.ResourceFacts.of(b.resource)):
        raise NotFound("Booking not found.")
