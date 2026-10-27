"""Worker jobs are idempotent; reports respect visibility and compute the right numbers."""

from datetime import timedelta

from sqlalchemy import func, select

from app.models import AuditLog, Booking, Notification
from app.services import bookings as bk
from app.services import reports
from app.worker import jobs
from tests.conftest import login, slot


def test_email_outbox_sends_once_and_retries_failures(db, world):
    from app.services.events import notify

    notify(db, world.student_qm.id, "x", title="Hello")
    notify(db, world.student_ml.id, "x", title="Hello")
    notify(db, world.student_sm.id, "x", title="In-app only", email=False)
    db.commit()
    sent = []

    def flaky(to, name, payload):
        if to.startswith("student_ml"):
            raise OSError("smtp down")
        sent.append(to)

    assert jobs.send_emails(db, sender=flaky) == 1
    assert jobs.send_emails(db, sender=flaky) == 0  # failed one is backing off, sent one is done
    assert sent == [world.student_qm.email]
    failed = db.scalar(select(Notification).where(Notification.user_id == world.student_ml.id))
    assert failed.email_attempts == 1 and "smtp down" in failed.last_email_error
    later = bk.utcnow() + timedelta(minutes=5)
    assert jobs.send_emails(db, now=later, sender=lambda *a: sent.append(a[0])) == 1


def test_reminders_once(db, world):
    r = world.resource(policy="institute_open")
    b = bk.create_booking(db, world.student_qm, r.id, *slot(1, 10))
    at = b.start - timedelta(minutes=30)
    assert jobs.send_reminders(db, now=at) == 1
    assert jobs.send_reminders(db, now=at) == 0


def test_complete_past_bookings(db, world):
    r = world.resource(policy="institute_open")
    b = bk.create_booking(db, world.student_qm, r.id, *slot(1))
    assert jobs.complete_past_bookings(db, now=b.end + timedelta(minutes=1)) == 1
    assert jobs.complete_past_bookings(db, now=b.end + timedelta(minutes=1)) == 0
    db.expire_all()
    assert db.get(Booking, b.id).status == "completed"


def test_usage_report_numbers_and_visibility(client, db, world):
    from datetime import time

    r = world.resource(world.qm, policy="institute_open", open_time=time(8), close_time=time(20))
    day_start, _ = slot(2, 8)
    bk.create_booking(db, world.student_qm, r.id, day_start + timedelta(hours=2), day_start + timedelta(hours=5))
    c = bk.create_booking(db, world.student_ml, r.id, day_start + timedelta(hours=6), day_start + timedelta(hours=7))
    bk.cancel_booking(db, world.student_ml, c.id, None)
    frm, to = day_start - timedelta(hours=8), day_start + timedelta(hours=16)  # one local day
    rep = reports.usage(db, world.prof_qm, frm, to)
    row = rep["resources"][0]
    assert rep["scope"] == "managed"
    assert row["booked_hours"] == 3 and row["open_hours"] == 12 and row["utilization_pct"] == 25.0
    assert row["cancellations"] == 1 and row["late_cancellations"] == 0
    # A student only sees their own history.
    own = reports.usage(db, world.student_ml, frm, to)
    assert own["scope"] == "own" and own["totals"]["booked_hours"] == 0 and own["totals"]["cancellations"] == 1
    # A professor of another lab sees nothing from this lab.
    assert reports.usage(db, world.prof_ml, frm, to)["resources"] == []
    # CSV export works through the API.
    login(client, world.prof_qm)
    q = {"from": frm.isoformat(), "to": to.isoformat()}
    resp = client.get("/api/v1/reports/usage.csv", params=q)
    assert resp.status_code == 200 and resp.text.splitlines()[0].startswith("resource_name,")
    raw = client.get("/api/v1/reports/usage.csv", params={**q, "raw": "true"})
    assert len(raw.text.strip().splitlines()) == 3  # header + 2 bookings


def test_audit_log_is_append_only(db, world):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    r = world.resource(policy="institute_open")
    bk.create_booking(db, world.student_qm, r.id, *slot(1))
    assert db.scalar(select(func.count()).select_from(AuditLog)) >= 1
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_log SET action = 'x'"))
    db.rollback()


def test_scheduler_tick_endpoint(client, world, monkeypatch):
    from app.settings import get_settings
    from app.worker.jobs import JOBS

    url = "/api/internal/jobs/tick"
    assert client.post(url).status_code == 404  # disabled until a key is configured
    monkeypatch.setattr(get_settings(), "cron_key", "s3cret-key")
    assert client.post(url, headers={"X-Relay-Cron-Key": "wrong"}).status_code == 403
    first = client.post(url, headers={"X-Relay-Cron-Key": "s3cret-key"})
    assert first.status_code == 200 and set(first.json()["ran"]) == set(JOBS)
    # Straight after, nothing is due yet: every job has an interval of at least 30 seconds.
    assert client.post(url, headers={"X-Relay-Cron-Key": "s3cret-key"}).json()["ran"] == {}
