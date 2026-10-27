from datetime import timedelta

import pytest
from sqlalchemy import select

from app.errors import Conflict, SlotConflict
from app.models import Booking, WaitlistEntry
from app.services import bookings as bk
from app.services import waitlist
from tests.conftest import slot


def test_offer_on_cancel_holds_the_slot_then_accept(db, world):
    r = world.resource(policy="institute_open")
    s, e = slot(2)
    b = bk.create_booking(db, world.student_qm, r.id, s, e)
    entry = waitlist.join(db, world.student_ml, r.id, s, e)
    bk.cancel_booking(db, world.student_qm, b.id, None)
    db.expire_all()
    assert db.get(WaitlistEntry, entry.id).status == "offered"
    # Nobody else can take it while the offer is open.
    with pytest.raises(SlotConflict):
        bk.create_booking(db, world.student_sm, r.id, s, e)
    db.rollback()
    booking = waitlist.accept(db, world.student_ml, entry.id)
    assert db.get(Booking, booking.id).status == "confirmed"


def test_expired_offer_passes_to_next(db, world):
    r = world.resource(policy="institute_open")
    s, e = slot(2)
    b = bk.create_booking(db, world.student_qm, r.id, s, e)
    first = waitlist.join(db, world.student_ml, r.id, s, e)
    second = waitlist.join(db, world.student_sm, r.id, s, e)
    bk.cancel_booking(db, world.student_qm, b.id, None)
    later = bk.utcnow() + timedelta(minutes=31)
    assert waitlist.expire_offers(db, later) == 1
    db.expire_all()
    assert db.get(WaitlistEntry, first.id).status == "expired"
    assert db.get(WaitlistEntry, second.id).status == "offered"
    assert waitlist.expire_offers(db, bk.utcnow()) == 0  # idempotent


def test_ineligible_entry_is_skipped(db, world):
    r = world.resource(world.qm, policy="institute_open")
    s, e = slot(2)
    b = bk.create_booking(db, world.student_qm, r.id, s, e)
    lost = waitlist.join(db, world.student_ml, r.id, s, e)
    nxt = waitlist.join(db, world.student_sm, r.id, s, e)
    r2 = db.get(type(r), r.id)
    r2.access_policy = "lab_only"  # student_ml loses access; student_sm too (other lab) -> nobody eligible
    db.commit()
    bk.cancel_booking(db, world.student_qm, b.id, None)
    db.expire_all()
    assert db.get(WaitlistEntry, lost.id).status == "waiting"
    assert db.get(WaitlistEntry, nxt.id).status == "waiting"
    assert db.scalar(select(Booking).where(Booking.status == "held")) is None


def test_cannot_waitlist_a_free_slot(db, world):
    r = world.resource(policy="institute_open")
    with pytest.raises(Conflict):
        waitlist.join(db, world.student_ml, r.id, *slot(2))
