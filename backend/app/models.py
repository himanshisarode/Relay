"""ORM models. The schema itself (constraints, indexes, extensions) is owned by alembic/versions/0001_initial.py;
these classes mirror it for querying."""

from datetime import date, datetime, time

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Text, Time, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSTZRANGE, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

TS = DateTime(timezone=True)


def _id() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def _created() -> Mapped[datetime]:
    return mapped_column(TS, server_default=func.now(), nullable=False)


def _fk(target: str, nullable: bool = False):
    return mapped_column(BigInteger, ForeignKey(target), nullable=nullable)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = _id()
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = _fk("users.id")
    csrf_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    user: Mapped[User] = relationship(lazy="joined")


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[int] = _id()
    user_id: Mapped[int] = _fk("users.id")
    purpose: Mapped[str] = mapped_column(Text)  # verify_email | password_reset
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(Text, unique=True)
    code: Mapped[str] = mapped_column(Text, unique=True)


class Lab(Base):
    __tablename__ = "labs"
    id: Mapped[int] = _id()
    department_id: Mapped[int] = _fk("departments.id")
    name: Mapped[str] = mapped_column(Text)
    department: Mapped[Department] = relationship(lazy="joined")


class DepartmentMember(Base):
    __tablename__ = "department_members"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("departments.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, default="member")  # member | dept_admin
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[int | None] = _fk("users.id", nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()


class LabMember(Base):
    __tablename__ = "lab_members"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    lab_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("labs.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, default="member")  # member | professor
    added_by: Mapped[int | None] = _fk("users.id", nullable=True)
    created_at: Mapped[datetime] = _created()


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[int] = _id()
    lab_id: Mapped[int] = _fk("labs.id")
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)  # instrument | meeting_room
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    access_policy: Mapped[str] = mapped_column(Text)
    accepts_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | maintenance | retired
    slot_granularity_min: Mapped[int] = mapped_column(Integer, default=30)
    min_duration_min: Mapped[int] = mapped_column(Integer, default=30)
    max_duration_min: Mapped[int] = mapped_column(Integer, default=240)
    open_time: Mapped[time] = mapped_column(Time, default=time(8))
    close_time: Mapped[time] = mapped_column(Time, default=time(20))
    max_advance_days: Mapped[int] = mapped_column(Integer, default=14)
    min_notice_min: Mapped[int] = mapped_column(Integer, default=30)
    weekly_quota_min: Mapped[int | None] = mapped_column(Integer)
    cancellation_cutoff_min: Mapped[int] = mapped_column(Integer, default=120)
    requires_checkin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    lab: Mapped[Lab] = relationship(lazy="joined")


class AccessRequest(Base):
    __tablename__ = "access_requests"
    id: Mapped[int] = _id()
    resource_id: Mapped[int] = _fk("resources.id")
    requester_id: Mapped[int] = _fk("users.id")
    justification: Mapped[str] = mapped_column(Text)
    requested_until: Mapped[date] = mapped_column(Date)
    supervisor_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    decided_by: Mapped[int | None] = _fk("users.id", nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    resource: Mapped[Resource] = relationship(lazy="joined")
    requester: Mapped[User] = relationship(lazy="joined", foreign_keys=[requester_id])


class AccessGrant(Base):
    __tablename__ = "access_grants"
    id: Mapped[int] = _id()
    resource_id: Mapped[int] = _fk("resources.id")
    user_id: Mapped[int] = _fk("users.id")
    request_id: Mapped[int | None] = _fk("access_requests.id", nullable=True)
    granted_by: Mapped[int] = _fk("users.id")
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_by: Mapped[int | None] = _fk("users.id", nullable=True)
    expiry_warned_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    resource: Mapped[Resource] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class BookingSeries(Base):
    __tablename__ = "booking_series"
    id: Mapped[int] = _id()
    resource_id: Mapped[int] = _fk("resources.id")
    owner_id: Mapped[int] = _fk("users.id")
    title: Mapped[str] = mapped_column(Text, default="")
    rrule_text: Mapped[str] = mapped_column(Text)
    tz: Mapped[str] = mapped_column(Text)
    local_start_time: Mapped[time] = mapped_column(Time)
    duration_min: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    materialized_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | ended | cancelled
    created_at: Mapped[datetime] = _created()


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = _id()
    resource_id: Mapped[int] = _fk("resources.id")
    user_id: Mapped[int] = _fk("users.id")
    series_id: Mapped[int | None] = _fk("booking_series.id", nullable=True)
    grant_id: Mapped[int | None] = _fk("access_grants.id", nullable=True)
    waitlist_entry_id: Mapped[int | None] = _fk("waitlist_entries.id", nullable=True)
    kind: Mapped[str] = mapped_column(Text, default="usage")  # usage | meeting | maintenance
    during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    status: Mapped[str] = mapped_column(Text, default="confirmed")
    purpose: Mapped[str] = mapped_column(Text, default="")
    checked_in_at: Mapped[datetime | None] = mapped_column(TS)
    cancelled_at: Mapped[datetime | None] = mapped_column(TS)
    cancelled_by: Mapped[int | None] = _fk("users.id", nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    reminded_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    resource: Mapped[Resource] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])

    @property
    def start(self) -> datetime:
        return self.during.lower  # type: ignore[return-value]

    @property
    def end(self) -> datetime:
        return self.during.upper  # type: ignore[return-value]


class BookingAttendee(Base):
    __tablename__ = "booking_attendees"
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    rsvp: Mapped[str | None] = mapped_column(Text)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    id: Mapped[int] = _id()
    resource_id: Mapped[int] = _fk("resources.id")
    user_id: Mapped[int] = _fk("users.id")
    desired_during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    status: Mapped[str] = mapped_column(Text, default="waiting")
    offer_expires_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = _id()
    user_id: Mapped[int] = _fk("users.id")
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(TS)
    emailed_at: Mapped[datetime | None] = mapped_column(TS)
    email_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_email_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = _id()
    actor_id: Mapped[int | None] = _fk("users.id", nullable=True)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()
