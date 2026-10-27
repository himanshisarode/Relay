"""Booking acceptance criteria AC-B1..B6 against a real PostgreSQL."""

import threading
from datetime import time, timedelta

import pytest
from sqlalchemy import select

from app.errors import ApiError, SlotConflict
from app.models import Booking
from app.services import bookings as bk
from tests.conftest import login, slot


def iso(dt):
    return dt.isoformat()


def test_ac_b1_concurrent_requests_exactly_one_wins(world, engine):
    """N threads, separate connections, same slot -> exactly one success, the rest SlotConflict."""
    from app.db import session_factory

    r = world.resource(policy="institute_open")
    start, end = slot(2)
    n = 12
    barrier = threading.Barrier(n)
    results: list[str] = []
    lock = threading.Lock()
    users = [world.student_qm, world.student_qm2, world.student_ml, world.student_sm, world.outsider, world.prof_ml] * 2

    def worker(u):
        with session_factory()() as s:
            barrier.wait()
            try:
                bk.create_booking(s, s.get(type(u), u.id), r.id, start, end)
                out = "ok"
            except SlotConflict:
                out = "conflict"
            except Exception as e:  # pragma: no cover
                out = f"error:{e!r}"
            with lock:
                results.append(out)

    threads = [threading.Thread(target=worker, args=(u,)) for u in users[:n]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("conflict") == n - 1, results


def test_ac_b1_via_api_201_then_409_with_suggestions(client, world):
    r = world.resource(policy="institute_open")
    start, end = slot(2)
    body = {"resource_id": r.id, "start": iso(start), "end": iso(end)}
    assert login(client, world.student_qm).post("/api/v1/bookings", json=body).status_code == 201
    second = login(client, world.student_ml).post("/api/v1/bookings", json=body)
    assert second.status_code == 409
    err = second.json()["error"]
    assert err["code"] == "slot_conflict" and len(err["details"]["next_available"]) == 3


def test_ac_b2_back_to_back_allowed(db, world):
    r = world.resource(policy="institute_open")
    s1, e1 = slot(2, 9)
    bk.create_booking(db, world.student_qm, r.id, s1, e1)
    bk.create_booking(db, world.student_ml, r.id, e1, e1 + timedelta(hours=1))
    with pytest.raises(SlotConflict):
        bk.create_booking(db, world.student_sm, r.id, e1 - timedelta(minutes=30), e1 + timedelta(minutes=30))


@pytest.mark.parametrize("hour,minutes,rule", [(7, 60, "opening_hours"), (10, 15, "min_duration"),
                                              (10, 300, "max_duration"), (19, 120, "opening_hours")])
def test_ac_b3_specific_rule_errors(client, world, hour, minutes, rule):
    r = world.resource(policy="institute_open", open_time=time(8),
                       close_time=time(20), slot_granularity_min=15, min_duration_min=30)
    start, end = slot(2, hour, minutes)
    resp = login(client, world.student_qm).post("/api/v1/bookings", json={"resource_id": r.id, "start": iso(start), "end": iso(end)})
    assert resp.status_code == 422 and resp.json()["error"]["details"]["rule"] == rule


def test_ac_b4_quota_reports_remaining(client, world):
    r = world.resource(policy="institute_open", weekly_quota_min=120)
    # Pick a Tuesday-Wednesday pair inside one local week, at least 2 days out.
    s1, e1 = slot(7, 9, 90)
    s1 = s1 - timedelta(days=s1.weekday() - 1)
    login(client, world.student_qm)
    assert client.post("/api/v1/bookings", json={"resource_id": r.id, "start": iso(s1), "end": iso(s1 + timedelta(minutes=90))}).status_code == 201
    s2 = s1 + timedelta(days=1)
    resp = client.post("/api/v1/bookings", json={"resource_id": r.id, "start": iso(s2), "end": iso(s2 + timedelta(minutes=60))})
    err = resp.json()["error"]
    assert resp.status_code == 422 and err["code"] == "quota_exceeded" and err["details"]["remaining_min"] == 30
    assert "30 minutes left" in err["message"]
    # The professor is exempt.
    login(client, world.prof_qm)
    assert client.post("/api/v1/bookings", json={"resource_id": r.id, "start": iso(s2), "end": iso(s2 + timedelta(minutes=180))}).status_code == 201


def test_ac_b5_failed_reschedule_leaves_original(db, world):
    r = world.resource(policy="institute_open")
    a = bk.create_booking(db, world.student_qm, r.id, *slot(2, 9))
    blocker_start, blocker_end = slot(2, 14)
    bk.create_booking(db, world.student_ml, r.id, blocker_start, blocker_end)
    with pytest.raises(SlotConflict):
        bk.reschedule(db, world.student_qm, a.id, blocker_start, blocker_end)
    db.expire_all()
    fresh = db.get(Booking, a.id)
    assert fresh.status == "confirmed" and fresh.start == slot(2, 9)[0]
    # A successful reschedule moves it.
    new = bk.reschedule(db, world.student_qm, a.id, *slot(3, 9))
    db.expire_all()
    assert db.get(Booking, a.id).status == "cancelled" and db.get(Booking, new.id).status == "confirmed"


def test_ac_b6_no_access_gets_403_and_no_write(client, world, db):
    r = world.resource(world.qm, policy="lab_only")
    start, end = slot(2)
    resp = login(client, world.student_ml).post("/api/v1/bookings", json={"resource_id": r.id, "start": iso(start), "end": iso(end)})
    assert resp.status_code == 403
    assert resp.json()["error"]["details"] == {"reason": "lab_members_only", "can_request_access": True}
    assert db.scalar(select(Booking).where(Booking.resource_id == r.id)) is None


def test_unverified_email_cannot_book(db, world):
    r = world.resource(policy="institute_open")
    with pytest.raises(ApiError) as e:
        bk.create_booking(db, world.unverified, r.id, *slot(2))
    assert e.value.status == 403


def test_privacy_on_calendar(client, world, db):
    r = world.resource(world.qm, policy="institute_open")
    start, end = slot(2)
    bk.create_booking(db, world.student_qm, r.id, start, end, "Secret sample")
    q = f"/api/v1/resources/{r.id}/availability?from={iso(start - timedelta(hours=1))}&to={iso(end)}"
    other = login(client, world.student_ml).get(q.replace("+", "%2B")).json()[0]
    assert other["label"] == "Booked · Quantum Materials" and other["purpose"] is None and other["user_name"] is None
    prof = login(client, world.prof_qm).get(q.replace("+", "%2B")).json()[0]
    assert prof["purpose"] == "Secret sample" and prof["user_name"] == world.student_qm.name


def test_cancel_by_professor_requires_reason_and_notifies(db, world):
    from app.models import Notification

    r = world.resource(world.qm, policy="institute_open")
    b = bk.create_booking(db, world.student_ml, r.id, *slot(2))
    with pytest.raises(ApiError):
        bk.cancel_booking(db, world.prof_qm, b.id, None)
    db.rollback()
    bk.cancel_booking(db, world.prof_qm, b.id, "Instrument needed for calibration")
    n = db.scalar(select(Notification).where(Notification.user_id == world.student_ml.id))
    assert n.type == "booking_cancelled"


def test_other_users_booking_is_404_not_403(db, world):
    from app.errors import NotFound

    r = world.resource(policy="institute_open")
    b = bk.create_booking(db, world.student_qm, r.id, *slot(2))
    with pytest.raises(NotFound):
        bk.cancel_booking(db, world.student_ml, b.id, "mine now")


def test_maintenance_block_lists_then_cancels_conflicts(db, world):
    from app.errors import Conflict

    r = world.resource(world.qm, policy="institute_open")
    b = bk.create_booking(db, world.student_ml, r.id, *slot(2, 10))
    start, end = slot(2, 9, 240)
    with pytest.raises(Conflict) as e:
        bk.create_maintenance(db, world.prof_qm, r.id, start, end, "Pump service", cancel_conflicts=False)
    assert [x["id"] for x in e.value.details["bookings"]] == [b.id]
    db.rollback()
    _, cancelled = bk.create_maintenance(db, world.prof_qm, r.id, start, end, "Pump service", cancel_conflicts=True)
    assert [c.id for c in cancelled] == [b.id]
    with pytest.raises(SlotConflict):
        bk.create_booking(db, world.student_qm, r.id, *slot(2, 11))


def test_inactive_resource_blocks_booking(db, world):
    r = world.resource(policy="institute_open", status="maintenance")
    with pytest.raises(ApiError) as e:
        bk.create_booking(db, world.prof_qm, r.id, *slot(2))
    assert e.value.details["reason"] == "resource_unavailable"
