"""Test setup. Pure-logic tests need nothing; tests using the `db`/`client` fixtures need a real PostgreSQL
(exclusion constraints and tstzrange don't exist elsewhere), given by RELAY_TEST_DATABASE_URL, e.g.

    RELAY_TEST_DATABASE_URL=postgresql+psycopg://relay:relay@localhost:5432/relay_test

The test database's public schema is dropped and rebuilt from migrations once per run.
"""

import os
from datetime import datetime, time, timedelta

import pytest

TEST_URL = os.environ.get("RELAY_TEST_DATABASE_URL")
os.environ.update({
    "RELAY_DATABASE_URL": TEST_URL or "postgresql+psycopg://invalid/none",
    "RELAY_COOKIE_SECURE": "false",
    "RELAY_RATE_LIMIT_ENABLED": "false",
    "RELAY_DEV_EXPOSE_TOKENS": "true",
    "RELAY_TIMEZONE": "Asia/Kolkata",
})

from sqlalchemy import text  # noqa: E402

TABLES = ("job_runs, audit_log, notifications, booking_attendees, bookings, waitlist_entries, booking_series, access_grants, "
          "access_requests, resources, lab_members, department_members, labs, departments, auth_tokens, sessions, users")


@pytest.fixture(scope="session")
def engine():
    if not TEST_URL:
        pytest.skip("RELAY_TEST_DATABASE_URL not set; skipping database tests")
    from alembic.config import Config

    from alembic import command
    from app.db import get_engine

    eng = get_engine()
    try:
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    except Exception as e:  # pragma: no cover - environment problem, not a test failure
        pytest.skip(f"cannot reach test database: {e}")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["database_url"] = TEST_URL
    command.upgrade(cfg, "head")
    return eng


@pytest.fixture
def db(engine):
    from app.auth.security import limiter
    from app.db import session_factory

    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    limiter.reset()
    s = session_factory()()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


# ---- builders -----------------------------------------------------------------------------------------------


class World:
    """Small org for tests: PHY (labs QM, SM) and CSA (lab ML), with people in every role."""

    PASSWORD = "correct-horse-battery"

    def __init__(self, db):
        from app.auth.security import hash_password
        from app.models import Department, DepartmentMember, Lab, LabMember, User

        self.db = db
        pw = hash_password(self.PASSWORD)

        def user(key, *, verified=True, superadmin=False):
            u = User(name=key.replace("_", " ").title(), email=f"{key}@test.local", password_hash=pw,
                     email_verified=verified, is_superadmin=superadmin)
            db.add(u)
            db.flush()
            setattr(self, key, u)
            return u

        self.phy = Department(code="PHY", name="Physics")
        self.csa = Department(code="CSA", name="Computer Science")
        db.add_all([self.phy, self.csa])
        db.flush()
        self.qm = Lab(department_id=self.phy.id, name="Quantum Materials")
        self.sm = Lab(department_id=self.phy.id, name="Soft Matter")
        self.ml = Lab(department_id=self.csa.id, name="Machine Learning")
        db.add_all([self.qm, self.sm, self.ml])
        db.flush()

        user("admin", superadmin=True)
        for key, lab, role in [("prof_qm", self.qm, "professor"), ("student_qm", self.qm, "member"),
                               ("student_qm2", self.qm, "member"), ("prof_ml", self.ml, "professor"),
                               ("student_ml", self.ml, "member"), ("student_sm", self.sm, "member")]:
            u = user(key)
            db.add(LabMember(user_id=u.id, lab_id=lab.id, role=role))
            db.add(DepartmentMember(user_id=u.id, department_id=lab.department_id, verified=True))
        hod = user("hod_phy")
        db.add(DepartmentMember(user_id=hod.id, department_id=self.phy.id, role="dept_admin", verified=True))
        user("outsider")
        user("unverified", verified=False)
        db.commit()

    def resource(self, lab=None, *, policy="department", type_="instrument", **rules):
        from app.models import Resource

        defaults = dict(slot_granularity_min=30, min_duration_min=30, max_duration_min=240, open_time=time(0),
                        close_time=time(0), max_advance_days=30, min_notice_min=0, weekly_quota_min=None,
                        cancellation_cutoff_min=120)
        r = Resource(lab_id=(lab or self.qm).id, name=f"R{datetime.now().timestamp()}", type=type_,
                     access_policy=policy, **{**defaults, **rules})
        self.db.add(r)
        self.db.commit()
        return r


@pytest.fixture
def world(db):
    return World(db)


def slot(days: int = 1, hour: int = 10, minutes: int = 60, minute: int = 0):
    """A future [start, end) in IST, `days` from today."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    d = datetime.now(tz).date() + timedelta(days=days)
    start = datetime.combine(d, time(hour, minute), tz)
    return start, start + timedelta(minutes=minutes)


def login(client, user_or_email, password=World.PASSWORD):
    email = user_or_email if isinstance(user_or_email, str) else user_or_email.email
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client
