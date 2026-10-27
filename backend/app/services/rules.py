"""Per-resource booking rules (spec 5.2). Pure functions; all times are aware datetimes, rules are evaluated
in the institute timezone because opening hours and slot boundaries are wall-clock concepts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.errors import RuleViolation


@dataclass(frozen=True)
class Rules:
    slot_granularity_min: int = 30
    min_duration_min: int = 30
    max_duration_min: int = 240
    open_time: time = time(8)
    close_time: time = time(20)
    max_advance_days: int = 14
    min_notice_min: int = 30
    weekly_quota_min: int | None = None
    cancellation_cutoff_min: int = 120

    @classmethod
    def of(cls, r) -> "Rules":
        return cls(**{f: getattr(r, f) for f in cls.__dataclass_fields__})

    @property
    def always_open(self) -> bool:
        return self.open_time == self.close_time


def _minutes(td: timedelta) -> int:
    return int(td.total_seconds() // 60)


def open_windows(rules: Rules, day: date, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """The bookable window(s) that start on `day` (local). A close before open means an overnight window."""
    if rules.always_open:
        start = datetime.combine(day, time(0), tz)
        return [(start, datetime.combine(day + timedelta(days=1), time(0), tz))]
    start = datetime.combine(day, rules.open_time, tz)
    end_day = day if rules.close_time > rules.open_time else day + timedelta(days=1)
    return [(start, datetime.combine(end_day, rules.close_time, tz))]


def within_opening_hours(rules: Rules, start: datetime, end: datetime, tz: ZoneInfo) -> bool:
    local_day = start.astimezone(tz).date()
    for d in (local_day - timedelta(days=1), local_day):
        for ws, we in open_windows(rules, d, tz):
            if ws <= start and end <= we:
                return True
    # A 24-hour resource accepts bookings that cross midnight.
    return rules.always_open


def validate(rules: Rules, start: datetime, end: datetime, now: datetime, tz: ZoneInfo, *, privileged: bool) -> None:
    """Raise RuleViolation with a specific `rule` detail for the first broken rule (AC-B3)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise RuleViolation("Times must include a timezone.", rule="naive_time")
    if end <= start:
        raise RuleViolation("The booking must end after it starts.", rule="end_before_start")

    duration = _minutes(end - start)
    if duration < rules.min_duration_min:
        raise RuleViolation(
            f"Bookings must be at least {rules.min_duration_min} minutes.",
            rule="min_duration",
            min_duration_min=rules.min_duration_min,
        )
    if duration > rules.max_duration_min:
        raise RuleViolation(
            f"Bookings can be at most {rules.max_duration_min} minutes.",
            rule="max_duration",
            max_duration_min=rules.max_duration_min,
        )

    g = rules.slot_granularity_min
    local = start.astimezone(tz)
    if (local.hour * 60 + local.minute) % g or local.second or local.microsecond or duration % g:
        raise RuleViolation(f"Bookings snap to {g}-minute slots.", rule="granularity", slot_granularity_min=g)

    if not within_opening_hours(rules, start, end, tz):
        raise RuleViolation(
            f"Outside opening hours ({rules.open_time:%H:%M}-{rules.close_time:%H:%M}).",
            rule="opening_hours",
            open_time=rules.open_time.strftime("%H:%M"),
            close_time=rules.close_time.strftime("%H:%M"),
        )

    if start < now:
        raise RuleViolation("That time is in the past.", rule="in_past")
    if not privileged:
        if start < now + timedelta(minutes=rules.min_notice_min):
            raise RuleViolation(
                f"Book at least {rules.min_notice_min} minutes ahead.",
                rule="min_notice",
                min_notice_min=rules.min_notice_min,
            )
        if start > now + timedelta(days=rules.max_advance_days):
            raise RuleViolation(
                f"You can book at most {rules.max_advance_days} days ahead.",
                rule="max_advance",
                max_advance_days=rules.max_advance_days,
            )


def week_start(dt: datetime, tz: ZoneInfo) -> datetime:
    """Monday 00:00 local of the week containing dt."""
    local = dt.astimezone(tz)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time(0), tz)


def minutes_by_week(start: datetime, end: datetime, tz: ZoneInfo) -> dict[date, int]:
    """Split [start, end) at local week boundaries; a booking over Sunday midnight counts in both weeks."""
    out: dict[date, int] = {}
    cur = start
    while cur < end:
        ws = week_start(cur, tz)
        nxt = min(end, datetime.combine(ws.date() + timedelta(days=7), time(0), tz))
        out[ws.date()] = out.get(ws.date(), 0) + _minutes(nxt - cur)
        cur = nxt
    return out


def is_late_cancel(rules: Rules, start: datetime, cancelled_at: datetime) -> bool:
    return cancelled_at > start - timedelta(minutes=rules.cancellation_cutoff_min)
