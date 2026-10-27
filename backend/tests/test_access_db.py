"""Access workflow acceptance criteria AC-R1..R5 against a real PostgreSQL."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.errors import ApiError, Conflict, Forbidden
from app.models import AccessGrant, AccessRequest, Booking, Notification
from app.services import access
from app.services import bookings as bk
from tests.conftest import login, slot

WHY = "Need it for a joint project on thin-film samples."


def until(days=30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_ac_r1_request_then_book_without_relogin(client, world):
    r = world.resource(world.qm, policy="department")
    login(client, world.student_ml)
    assert client.get(f"/api/v1/resources/{r.id}").json()["my_access"] == "request_possible"
    req = client.post(f"/api/v1/resources/{r.id}/access-requests", json={"justification": WHY, "requested_until": until()})
    assert req.status_code == 201
    assert client.get(f"/api/v1/resources/{r.id}").json()["my_access"] == "request_pending"

    prof = login(type(client)(client.app), world.prof_qm)
    inbox = prof.get("/api/v1/access-requests?to_decide=true").json()
    assert [i["id"] for i in inbox] == [req.json()["id"]]
    assert inbox[0]["requester_departments"][0]["code"] == "CSA"
    assert prof.post(f"/api/v1/access-requests/{inbox[0]['id']}/approve", json={"note": "ok"}).status_code == 200

    # Same session, no re-login.
    assert client.get(f"/api/v1/resources/{r.id}").json()["my_access"] == "allowed"
    s, e = slot(2)
    assert client.post("/api/v1/bookings", json={"resource_id": r.id, "start": s.isoformat(), "end": e.isoformat()}).status_code == 201


def test_ac_r2_second_pending_request_rejected(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    with pytest.raises(Conflict) as e:
        access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    assert e.value.code == "request_pending"


def test_cannot_request_with_active_grant_or_existing_access(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    access.approve(db, world.prof_qm, req.id, None, None)
    with pytest.raises(Conflict) as e:
        access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    assert e.value.code == "already_granted"
    with pytest.raises(Conflict) as e:
        access.create_request(db, world.student_qm, world.resource(world.qm, policy="lab_only").id, WHY,
                              date.today() + timedelta(days=10), None)
    assert e.value.code == "already_allowed"


def test_ac_r3_cannot_decide_own_request_even_as_professor_elsewhere(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.prof_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    with pytest.raises(ApiError):
        access.approve(db, world.prof_ml, req.id, None, None)
    db.rollback()
    with pytest.raises(ApiError):
        access.reject(db, world.prof_ml, req.id, "no thanks")
    db.rollback()
    # The owning lab's professor and the department admin can.
    assert [x.id for x in access.to_decide(db, world.hod_phy)] == [req.id]
    assert access.to_decide(db, world.prof_ml) == []


def test_professor_can_only_shorten(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    with pytest.raises(ApiError):
        access.approve(db, world.prof_qm, req.id, date.today() + timedelta(days=20), None)
    db.rollback()
    g = access.approve(db, world.prof_qm, req.id, date.today() + timedelta(days=5), "Five days only")
    assert g.expires_at.date() >= date.today() + timedelta(days=5)


def test_reject_needs_reason_and_notifies(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    with pytest.raises(ApiError):
        access.reject(db, world.prof_qm, req.id, "")
    db.rollback()
    access.reject(db, world.prof_qm, req.id, "Instrument is fully booked this term")
    n = db.scalar(select(Notification).where(Notification.user_id == world.student_ml.id,
                                             Notification.type == "access_request_rejected"))
    assert "fully booked" in n.payload["body"]


def test_ac_r4_expired_grant_blocks_new_bookings_keeps_history(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    g = access.approve(db, world.prof_qm, req.id, None, None)
    b = bk.create_booking(db, world.student_ml, r.id, *slot(1))
    db.execute(update(AccessGrant).where(AccessGrant.id == g.id).values(expires_at=datetime.now(UTC)))
    db.commit()
    with pytest.raises(Forbidden):
        bk.create_booking(db, world.student_ml, r.id, *slot(2))
    db.rollback()
    assert b.id in [x.id for x in bk.my_bookings(db, world.student_ml, None, None, True)]


def test_booking_cannot_outlast_grant(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=2), None)
    access.approve(db, world.prof_qm, req.id, None, None)
    with pytest.raises(ApiError) as e:
        bk.create_booking(db, world.student_ml, r.id, *slot(5))
    assert e.value.details["rule"] == "beyond_grant"


def test_ac_r5_revoke_cancels_future_bookings_and_notifies(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=20), None)
    g = access.approve(db, world.prof_qm, req.id, None, None)
    b1 = bk.create_booking(db, world.student_ml, r.id, *slot(2))
    b2 = bk.create_booking(db, world.student_ml, r.id, *slot(3))
    _, cancelled = access.revoke(db, world.prof_qm, g.id, "Misuse of the instrument")
    assert {b.id for b in cancelled} == {b1.id, b2.id}
    db.expire_all()
    assert {db.get(Booking, i).status for i in (b1.id, b2.id)} == {"cancelled"}
    n = db.scalar(select(Notification).where(Notification.user_id == world.student_ml.id, Notification.type == "access_revoked"))
    assert n.payload["cancelled_booking_ids"] == [b1.id, b2.id] or set(n.payload["cancelled_booking_ids"]) == {b1.id, b2.id}
    with pytest.raises(Forbidden):
        bk.create_booking(db, world.student_ml, r.id, *slot(4))


def test_stale_requests_expire_idempotently(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    req = access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    later = datetime.now(UTC) + timedelta(days=31)
    assert access.expire_stale_requests(db, later) == 1
    assert access.expire_stale_requests(db, later) == 0
    assert db.get(AccessRequest, req.id).status == "expired"


def test_deciders_notified_on_submit(db, world):
    r = world.resource(world.qm, policy="institute_approval")
    access.create_request(db, world.student_ml, r.id, WHY, date.today() + timedelta(days=10), None)
    to = set(db.scalars(select(Notification.user_id).where(Notification.type == "access_request_submitted")))
    assert to == {world.prof_qm.id, world.hod_phy.id}
