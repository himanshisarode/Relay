"""Recurring lab meetings (spec 6). The rule is stored in local time with its timezone, and occurrences are
materialized as ordinary booking rows for the next 12 weeks so the overlap constraint needs no special cases."""

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar, Event
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError, Conflict, NotFound, RuleViolation, SlotConflict
from app.models import Booking, BookingAttendee, BookingSeries, User
from app.services import bookings as bk
from app.services import permissions, rules
from app.services.events import audit, notify
from app.settings import get_settings

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
Mode = Literal["all_or_nothing", "skip_conflicts"]


def build_rrule(weekdays: list[int], interval: int, ends_on: date | None, count: int | None) -> str:
    if not weekdays or any(d not in range(7) for d in weekdays):
        raise RuleViolation("Pick at least one weekday.", rule="weekdays")
    if interval not in (1, 2):
        raise RuleViolation("Series repeat weekly or fortnightly.", rule="interval")
    if (ends_on is None) == (count is None):
        raise RuleViolation("Give either an end date or a number of occurrences.", rule="series_end")
    parts = [f"FREQ=WEEKLY;INTERVAL={interval};BYDAY={','.join(DAYS[d] for d in sorted(set(weekdays)))}"]
    if count is not None:
        if not 1 <= count <= 200:
            raise RuleViolation("Between 1 and 200 occurrences.", rule="count")
        parts.append(f"COUNT={count}")
    else:
        parts.append(f"UNTIL={ends_on:%Y%m%d}T235959")
    return ";".join(parts)


def occurrences(s: BookingSeries, frm: date, to: date) -> list[tuple[datetime, datetime]]:
    """Occurrences whose local date is in [frm, to], as aware datetimes in the series' own zone."""
    tz = ZoneInfo(s.tz)
    dtstart = datetime.combine(s.starts_on, s.local_start_time)
    rule = rrulestr(s.rrule_text, dtstart=dtstart)
    lo = datetime.combine(frm, time(0))
    hi = datetime.combine(to, time(23, 59, 59))
    out = []
    for naive in rule.between(lo, hi, inc=True):
        start = naive.replace(tzinfo=tz)  # wall-clock time is preserved across DST changes
        out.append((start, start + timedelta(minutes=s.duration_min)))
    return out


def _horizon() -> date:
    return bk.utcnow().astimezone(get_settings().tz).date() + timedelta(weeks=get_settings().series_horizon_weeks)


def _materialize(
    db: Session, s: BookingSeries, owner: User, frm: date, to: date, attendee_ids: list[int]
) -> tuple[list[Booking], list[dict]]:
    resource = bk.get_resource(db, s.resource_id)
    decision = permissions.require_book(db, owner, resource)
    rl = rules.Rules.of(resource)
    made, skipped = [], []
    now = bk.utcnow()
    for start, end in occurrences(s, frm, to):
        if start < now:
            continue
        try:
            # The series horizon replaces max_advance_days for occurrences, so validate as privileged for that rule.
            rules.validate(rl, start, end, now, get_settings().tz, privileged=True)
            b = Booking(
                resource_id=resource.id,
                user_id=owner.id,
                series_id=s.id,
                grant_id=decision.grant_id,
                kind="meeting" if resource.type == "meeting_room" else "usage",
                during=bk._span(start, end),
                status="confirmed",
                purpose=s.title,
            )
            bk._insert(db, b, resource, s.duration_min, start)
        except (SlotConflict, RuleViolation) as e:
            skipped.append({"start": start.isoformat(), "end": end.isoformat(), "reason": e.code})
            continue
        for uid in attendee_ids:
            db.add(BookingAttendee(booking_id=b.id, user_id=uid))
        made.append(b)
    return made, skipped


def ics_for(s: BookingSeries, resource_name: str, location: str, organizer: User) -> str:
    cal = Calendar()
    cal.add("prodid", "-//Relay//Lab booking//EN")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST")
    ev = Event()
    ev.add("uid", f"series-{s.id}@relay")
    ev.add("summary", s.title or f"Meeting in {resource_name}")
    start = datetime.combine(s.starts_on, s.local_start_time, ZoneInfo(s.tz))
    ev.add("dtstart", start)
    ev.add("dtend", start + timedelta(minutes=s.duration_min))
    ev.add("location", location or resource_name)
    ev.add("organizer", f"mailto:{organizer.email}")
    ev.add("dtstamp", bk.utcnow())
    ev["rrule"] = s.rrule_text.replace("T235959", "T235959Z") if "UNTIL" in s.rrule_text else s.rrule_text
    cal.add_component(ev)
    return cal.to_ical().decode()


def create(
    db: Session,
    owner: User,
    resource_id: int,
    *,
    title: str,
    weekdays: list[int],
    interval: int,
    local_start_time: time,
    duration_min: int,
    starts_on: date,
    ends_on: date | None,
    count: int | None,
    mode: Mode,
    attendee_emails: list[str],
) -> tuple[BookingSeries, list[Booking], list[dict]]:
    resource = bk.get_resource(db, resource_id)
    if resource.type != "meeting_room":
        raise RuleViolation("Recurring series are for meeting rooms.", rule="not_meeting_room")
    permissions.require_book(db, owner, resource)
    attendees = []
    for email in {e.strip().lower() for e in attendee_emails if e.strip()}:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            raise NotFound(f"No account for {email}.")
        if u.id != owner.id:
            attendees.append(u)
    s = BookingSeries(
        resource_id=resource.id,
        owner_id=owner.id,
        title=title.strip(),
        rrule_text=build_rrule(weekdays, interval, ends_on, count),
        tz=get_settings().timezone,
        local_start_time=local_start_time,
        duration_min=duration_min,
        starts_on=starts_on,
        ends_on=ends_on,
        max_occurrences=count,
        materialized_until=min(_horizon(), ends_on or _horizon()),
    )
    db.add(s)
    db.flush()
    made, skipped = _materialize(db, s, owner, starts_on, s.materialized_until, [a.id for a in attendees])
    if mode == "all_or_nothing" and skipped:
        db.rollback()
        raise Conflict(
            f"{len(skipped)} occurrence(s) clash with existing bookings or rules; nothing was booked.",
            code="series_conflicts",
            skipped=skipped,
        )
    if not made:
        db.rollback()
        raise Conflict("None of the occurrences could be booked.", code="series_conflicts", skipped=skipped)
    audit(db, owner.id, "series.create", "booking_series", s.id, created=len(made), skipped=len(skipped))
    if attendees:
        ics = ics_for(s, resource.name, resource.location, owner)
        notify(
            db,
            [a.id for a in attendees],
            "meeting_invite",
            title=f"{owner.name} invited you: {s.title or 'meeting'}",
            body=f"Starts {bk.fmt(made[0].start)} in {resource.name}, repeating. The calendar invite is attached.",
            link="/bookings",
            series_id=s.id,
            ics=ics,
        )
    db.commit()
    return s, made, skipped


def cancel(db: Session, actor: User, series_id: int, scope: Literal["this", "future"], booking_id: int) -> list[Booking]:
    s = db.get(BookingSeries, series_id)
    if s is None:
        raise NotFound("Series not found.")
    anchor = bk.get_booking(db, booking_id, lock=True)
    if anchor.series_id != s.id:
        raise NotFound("That booking is not part of this series.")
    if s.owner_id != actor.id:
        permissions.require_manage(db, actor, anchor.resource)
    if scope == "this":
        bk.cancel_booking_tx(db, actor, anchor, "Occurrence cancelled" if s.owner_id == actor.id else "Cancelled by lab")
        cancelled = [anchor]
    else:
        cancelled = list(
            db.scalars(
                select(Booking)
                .where(
                    Booking.series_id == s.id,
                    Booking.status.in_(bk.ACTIVE),
                    func.lower(Booking.during) >= anchor.start,
                )
                .with_for_update(of=Booking)
            )
        )
        for b in cancelled:
            bk.cancel_booking_tx(db, actor, b, "Series ended", notify_owner=s.owner_id != actor.id)
        last_day = anchor.start.astimezone(ZoneInfo(s.tz)).date() - timedelta(days=1)
        s.ends_on = last_day if s.ends_on is None else min(s.ends_on, last_day)
        s.status = "ended"
        attendees = set(db.scalars(select(BookingAttendee.user_id).where(BookingAttendee.booking_id == anchor.id)))
        if attendees:
            notify(
                db,
                attendees,
                "meeting_cancelled",
                title=f"{s.title or 'Meeting'} series cancelled",
                body=f"From {bk.fmt(anchor.start)} onwards.",
                series_id=s.id,
            )
    audit(db, actor.id, f"series.cancel_{scope}", "booking_series", s.id, booking_ids=[b.id for b in cancelled])
    db.commit()
    return cancelled


def extend_all(db: Session, now: datetime | None = None) -> int:
    """Worker job: roll each active series forward to the 12-week horizon. Idempotent via materialized_until."""
    horizon = _horizon()
    extended = 0
    for s in db.scalars(
        select(BookingSeries).where(BookingSeries.status == "active", BookingSeries.materialized_until < horizon)
    ):
        target = min(horizon, s.ends_on or horizon)
        if target <= s.materialized_until:
            s.status = "ended" if s.ends_on and s.ends_on <= s.materialized_until else s.status
            continue
        owner = db.get(User, s.owner_id)
        attendees = list(
            db.scalars(
                select(BookingAttendee.user_id)
                .join(Booking, Booking.id == BookingAttendee.booking_id)
                .where(Booking.series_id == s.id)
                .distinct()
            )
        )
        try:
            made, skipped = _materialize(db, s, owner, s.materialized_until + timedelta(days=1), target, attendees)
        except ApiError:
            # Owner lost access: stop the series rather than failing every run.
            s.status = "ended"
            notify(
                db,
                owner.id,
                "series_stopped",
                title=f"Your series '{s.title}' stopped",
                body="You no longer have access to the room.",
                series_id=s.id,
            )
            continue
        if s.max_occurrences is not None:
            total = db.scalar(select(func.count()).where(Booking.series_id == s.id))
            if total >= s.max_occurrences:
                s.status = "ended"
        s.materialized_until = target
        extended += len(made)
        if skipped:
            notify(
                db,
                owner.id,
                "series_skipped",
                title=f"{len(skipped)} occurrence(s) of '{s.title}' could not be booked",
                body=", ".join(x["start"][:16].replace("T", " ") for x in skipped),
                series_id=s.id,
            )
    db.commit()
    return extended
