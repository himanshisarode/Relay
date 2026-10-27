"""Recurring series: AC-S1 (pure) and AC-S2/S3 (database)."""

from datetime import date, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.errors import Conflict, RuleViolation
from app.models import Booking, BookingAttendee, Notification
from app.services import bookings as bk
from app.services import series
from tests.conftest import slot


def fake_series(tz: str, rrule: str, starts_on: date, at: time = time(10), minutes: int = 60):
    return SimpleNamespace(tz=tz, rrule_text=rrule, starts_on=starts_on, local_start_time=at, duration_min=minutes)


def test_ac_s1_twelve_weekly_occurrences_keep_wall_clock_across_dst():
    # London leaves summer time on 25 Oct 2026; a 10:00 meeting must stay at 10:00 local.
    rule = series.build_rrule([2], 1, None, 12)  # Wednesdays, 12 times
    s = fake_series("Europe/London", rule, date(2026, 10, 7))
    occ = series.occurrences(s, date(2026, 10, 1), date(2027, 1, 31))
    assert len(occ) == 12
    assert {o[0].hour for o in occ} == {10}
    utc_hours = {o[0].astimezone(ZoneInfo("UTC")).hour for o in occ}
    assert utc_hours == {9, 10}  # 09:00 UTC in BST, 10:00 UTC in GMT


def test_fortnightly_multiple_days():
    rule = series.build_rrule([0, 3], 2, date(2026, 11, 30), None)
    occ = series.occurrences(fake_series("Asia/Kolkata", rule, date(2026, 11, 2)), date(2026, 11, 1), date(2026, 12, 31))
    assert [o[0].date().isoformat() for o in occ] == ["2026-11-02", "2026-11-05", "2026-11-16", "2026-11-19", "2026-11-30"]


@pytest.mark.parametrize(
    "args", [([], 1, None, 3), ([1], 3, None, 3), ([1], 1, None, None), ([1], 1, date(2026, 12, 1), 4), ([9], 1, None, 2)]
)
def test_rrule_validation(args):
    with pytest.raises(RuleViolation):
        series.build_rrule(*args)


# ---- database -------------------------------------------------------------------------------------------------


def _room(world):
    return world.resource(world.qm, policy="lab_only", type_="meeting_room", max_advance_days=60, weekly_quota_min=None)


def _start_day(offset=2):
    return slot(offset)[0].date()


def _mk(db, world, room, mode="skip_conflicts", count=4, attendees=()):
    d = _start_day()
    return series.create(db, world.prof_qm, room.id, title="Group meeting", weekdays=[d.weekday()], interval=1,
                         local_start_time=time(16), duration_min=60, starts_on=d, ends_on=None, count=count, mode=mode,
                         attendee_emails=list(attendees))


def test_series_creates_occurrences_and_invites(db, world):
    room = _room(world)
    s, made, skipped = _mk(db, world, room, attendees=[world.student_qm.email])
    assert len(made) == 4 and not skipped
    assert db.scalar(select(BookingAttendee).where(BookingAttendee.user_id == world.student_qm.id)) is not None
    invite = db.scalar(select(Notification).where(Notification.type == "meeting_invite"))
    assert "BEGIN:VCALENDAR" in invite.payload["ics"] and "RRULE" in invite.payload["ics"]


def test_ac_s2_cancel_one_occurrence(db, world):
    room = _room(world)
    s, made, _ = _mk(db, world, room)
    series.cancel(db, world.prof_qm, s.id, "this", made[1].id)
    db.expire_all()
    assert [db.get(Booking, b.id).status for b in made] == ["confirmed", "cancelled", "confirmed", "confirmed"]


def test_cancel_this_and_future(db, world):
    room = _room(world)
    s, made, _ = _mk(db, world, room)
    series.cancel(db, world.prof_qm, s.id, "future", made[2].id)
    db.expire_all()
    assert [db.get(Booking, b.id).status for b in made] == ["confirmed", "confirmed", "cancelled", "cancelled"]


def test_ac_s3_all_or_nothing_with_one_conflict_books_nothing(db, world):
    room = _room(world)
    d = _start_day() + timedelta(days=7)
    blocker_start = slot((d - slot(0)[0].date()).days, 16)[0]
    bk.create_booking(db, world.student_qm, room.id, blocker_start, blocker_start + timedelta(minutes=30))
    with pytest.raises(Conflict) as e:
        _mk(db, world, room, mode="all_or_nothing")
    assert len(e.value.details["skipped"]) == 1
    assert db.scalar(select(Booking).where(Booking.series_id.is_not(None))) is None
    # skip_conflicts books the other three and lists the skipped date.
    _, made, skipped = _mk(db, world, room, mode="skip_conflicts")
    assert len(made) == 3 and len(skipped) == 1


def test_meetings_ignore_quota(db, world):
    room = world.resource(world.qm, policy="lab_only", type_="meeting_room", weekly_quota_min=30)
    _, made, _ = _mk(db, world, room)
    assert len(made) == 4


def test_series_only_for_meeting_rooms(db, world):
    with pytest.raises(RuleViolation):
        _mk(db, world, world.resource(world.qm))
