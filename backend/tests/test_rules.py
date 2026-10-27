"""Booking rule boundaries (spec 5.2, AC-B3) and week splitting for quotas."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.errors import RuleViolation
from app.services.rules import Rules, is_late_cancel, minutes_by_week, validate, within_opening_hours

IST = ZoneInfo("Asia/Kolkata")
RULES = Rules(slot_granularity_min=30, min_duration_min=30, max_duration_min=240, open_time=time(8),
              close_time=time(20), max_advance_days=14, min_notice_min=30)
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=IST)  # a Monday


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, 2, hh, mm, tzinfo=IST) + timedelta(days=day)


def rule_of(start, end, rules=RULES, privileged=False, now=NOW):
    try:
        validate(rules, start, end, now, IST, privileged=privileged)
    except RuleViolation as e:
        return e.details["rule"]
    return None


@pytest.mark.parametrize("start,end,expected", [
    (at(1, 10), at(1, 10, 30), None),               # exactly the minimum
    (at(1, 10), at(1, 10), "end_before_start"),
    (at(1, 10), at(1, 9), "end_before_start"),
    (at(1, 10), at(1, 14), None),                   # exactly the maximum
    (at(1, 10), at(1, 14, 30), "max_duration"),
    (at(1, 8), at(1, 8, 30), None),                 # starts at opening
    (at(1, 19, 30), at(1, 20), None),               # ends exactly at closing
    (at(1, 7, 30), at(1, 8, 30), "opening_hours"),
    (at(1, 19, 30), at(1, 20, 30), "opening_hours"),
    (at(1, 10, 15), at(1, 10, 45), "granularity"),
    (at(1, 10), at(1, 10, 45), "granularity"),
    (at(0, 8), at(0, 9), "in_past"),
    (at(0, 9, 0), at(0, 10), "min_notice"),
    (at(0, 9, 30), at(0, 10), None),                # exactly the minimum notice
    (at(14, 9), at(14, 10), None),                  # exactly max_advance_days ahead
    (at(15, 9), at(15, 10), "max_advance"),
])
def test_boundaries(start, end, expected):
    assert rule_of(start, end) == expected


def test_min_duration():
    r = Rules(min_duration_min=60, slot_granularity_min=30)
    assert rule_of(at(1, 10), at(1, 10, 30), rules=r) == "min_duration"


def test_privileged_skips_notice_and_advance_but_not_hours():
    assert rule_of(at(0, 9), at(0, 10), privileged=True) is None
    assert rule_of(at(30, 9), at(30, 10), privileged=True) is None
    assert rule_of(at(1, 21), at(1, 21, 30), privileged=True) == "opening_hours"
    assert rule_of(at(0, 8), at(0, 9), privileged=True) == "in_past"


def test_naive_times_rejected():
    with pytest.raises(RuleViolation):
        validate(RULES, datetime(2026, 11, 3, 10), datetime(2026, 11, 3, 11), NOW, IST, privileged=False)


def test_utc_input_is_judged_in_local_time():
    # 04:30 UTC is 10:00 IST: inside opening hours even though 04:30 is not.
    s = datetime(2026, 11, 3, 4, 30, tzinfo=ZoneInfo("UTC"))
    assert rule_of(s, s + timedelta(hours=1)) is None


def test_always_open_resource_accepts_overnight():
    r = Rules(open_time=time(0), close_time=time(0), slot_granularity_min=60, max_duration_min=1440)
    assert within_opening_hours(r, at(1, 22), at(2, 6), IST)
    assert rule_of(at(1, 22), at(2, 6), rules=r) is None


def test_overnight_window():
    r = Rules(open_time=time(22), close_time=time(6), max_duration_min=480)
    assert within_opening_hours(r, at(1, 23), at(2, 5), IST)
    assert within_opening_hours(r, at(2, 1), at(2, 3), IST)  # inside the window that began the night before
    assert not within_opening_hours(r, at(1, 20), at(1, 23), IST)


def test_minutes_by_week_splits_at_monday_midnight():
    sun = datetime(2026, 11, 8, 23, 0, tzinfo=IST)
    weeks = minutes_by_week(sun, sun + timedelta(hours=2), IST)
    assert weeks == {date(2026, 11, 2): 60, date(2026, 11, 9): 60}


def test_late_cancel():
    r = Rules(cancellation_cutoff_min=120)
    start = at(1, 12)
    assert not is_late_cancel(r, start, at(1, 10))
    assert is_late_cancel(r, start, at(1, 10, 1))
