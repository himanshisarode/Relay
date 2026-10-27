"""Usage reports (spec 8). Visibility: professors see their labs, department admins their department,
super admins everything, everyone else only their own bookings."""

import csv
import io
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.errors import RuleViolation
from app.models import Booking, Lab, Resource, User
from app.services import permissions, rules
from app.settings import get_settings


def _scope(db: Session, viewer: User, stmt, *, user_id: int | None):
    facts = permissions.load_facts(db, viewer)
    if facts.is_superadmin:
        return stmt.where(Booking.user_id == user_id) if user_id else stmt, "all"
    if facts.professor_lab_ids or facts.admin_department_ids:
        stmt = stmt.where(or_(Lab.id.in_(facts.professor_lab_ids), Lab.department_id.in_(facts.admin_department_ids)))
        return (stmt.where(Booking.user_id == user_id) if user_id else stmt), "managed"
    return stmt.where(Booking.user_id == viewer.id), "own"


def _clip(b: Booking, frm: datetime, to: datetime) -> float:
    s, e = max(b.start, frm), min(b.end, to)
    return max(0.0, (e - s).total_seconds() / 3600)


def open_hours(r: Resource, frm: datetime, to: datetime) -> float:
    tz = get_settings().tz
    rl = rules.Rules.of(r)
    total = 0.0
    d = frm.astimezone(tz).date() - timedelta(days=1)
    while d <= to.astimezone(tz).date():
        for ws, we in rules.open_windows(rl, d, tz):
            s, e = max(ws, frm), min(we, to)
            if e > s:
                total += (e - s).total_seconds() / 3600
        d += timedelta(days=1)
    return total


def bookings_in_range(
    db: Session, viewer: User, frm: datetime, to: datetime, *, resource_id=None, lab_id=None, user_id=None
) -> tuple[list[Booking], str]:
    if to <= frm or to - frm > timedelta(days=366):
        raise RuleViolation("Pick a range of at most one year.", rule="range")
    stmt = (
        select(Booking)
        .join(Resource, Resource.id == Booking.resource_id)
        .join(Lab, Lab.id == Resource.lab_id)
        .where(Booking.during.op("&&")(_range(frm, to)))
    )
    if resource_id:
        stmt = stmt.where(Booking.resource_id == resource_id)
    if lab_id:
        stmt = stmt.where(Resource.lab_id == lab_id)
    stmt, scope = _scope(db, viewer, stmt, user_id=user_id)
    return list(db.scalars(stmt.order_by(Booking.during))), scope


def _range(frm, to):
    return Range(frm, to, bounds="[)")


def usage(db: Session, viewer: User, frm: datetime, to: datetime, **filters) -> dict:
    items, scope = bookings_in_range(db, viewer, frm, to, **filters)
    per: dict[int, dict] = {}
    daily: dict[str, float] = {}
    tz = get_settings().tz
    for b in items:
        r = b.resource
        row = per.setdefault(
            r.id,
            {
                "resource_id": r.id,
                "resource_name": r.name,
                "lab_name": r.lab.name,
                "type": r.type,
                "booked_hours": 0.0,
                "maintenance_hours": 0.0,
                "bookings": 0,
                "cancellations": 0,
                "late_cancellations": 0,
                "no_shows": 0,
                "unique_users": set(),
            },
        )
        if b.kind == "maintenance":
            if b.status in ("confirmed", "completed"):
                row["maintenance_hours"] += _clip(b, frm, to)
            continue
        if b.status == "cancelled":
            row["cancellations"] += 1
            if (
                b.cancelled_by == b.user_id
                and b.cancelled_at
                and rules.is_late_cancel(rules.Rules.of(r), b.start, b.cancelled_at)
            ):
                row["late_cancellations"] += 1
            continue
        if b.status == "held":
            continue
        if b.status == "no_show":
            row["no_shows"] += 1
        hours = _clip(b, frm, to)
        row["booked_hours"] += hours
        row["bookings"] += 1
        row["unique_users"].add(b.user_id)
        day = b.start.astimezone(tz).date().isoformat()
        daily[day] = daily.get(day, 0.0) + hours

    resources = {b.resource_id: b.resource for b in items}
    rows = []
    for rid, row in per.items():
        available = max(0.0, open_hours(resources[rid], frm, to) - row["maintenance_hours"])
        row["open_hours"] = round(available, 2)
        row["utilization_pct"] = round(100 * row["booked_hours"] / available, 1) if available and scope != "own" else None
        row["booked_hours"] = round(row["booked_hours"], 2)
        row["maintenance_hours"] = round(row["maintenance_hours"], 2)
        row["unique_users"] = len(row["unique_users"])
        rows.append(row)
    rows.sort(key=lambda r: -r["booked_hours"])
    d, end = frm.astimezone(tz).date(), (to - timedelta(microseconds=1)).astimezone(tz).date()
    series = []
    while d <= end:
        series.append({"date": d.isoformat(), "hours": round(daily.get(d.isoformat(), 0.0), 2)})
        d += date.resolution
    totals = {
        k: sum(r[k] for r in rows) for k in ("booked_hours", "bookings", "cancellations", "late_cancellations", "no_shows")
    }
    totals["booked_hours"] = round(totals["booked_hours"], 2)
    open_total = sum(r["open_hours"] for r in rows)
    totals["utilization_pct"] = (
        round(100 * totals["booked_hours"] / open_total, 1) if open_total and scope != "own" else None
    )
    return {"scope": scope, "from": frm, "to": to, "totals": totals, "resources": rows, "daily": series}


def usage_csv(report: dict) -> str:
    buf = io.StringIO()
    cols = [
        "resource_name",
        "lab_name",
        "type",
        "booked_hours",
        "open_hours",
        "utilization_pct",
        "maintenance_hours",
        "bookings",
        "unique_users",
        "cancellations",
        "late_cancellations",
        "no_shows",
    ]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(report["resources"])
    return buf.getvalue()


def raw_csv(db: Session, viewer: User, frm: datetime, to: datetime, **filters) -> str:
    items, scope = bookings_in_range(db, viewer, frm, to, **filters)
    tz = get_settings().tz
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "booking_id",
            "resource",
            "lab",
            "user",
            "kind",
            "status",
            "start_local",
            "end_local",
            "hours",
            "purpose",
            "cancelled_at_local",
            "cancel_reason",
        ]
    )
    for b in items:
        w.writerow(
            [
                b.id,
                b.resource.name,
                b.resource.lab.name,
                b.user.name,
                b.kind,
                b.status,
                b.start.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                b.end.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                round((b.end - b.start).total_seconds() / 3600, 2),
                b.purpose,
                b.cancelled_at.astimezone(tz).strftime("%Y-%m-%d %H:%M") if b.cancelled_at else "",
                b.cancel_reason or "",
            ]
        )
    return buf.getvalue()
