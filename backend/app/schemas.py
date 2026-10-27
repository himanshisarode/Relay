"""Request and response bodies. Datetimes are ISO 8601 with offset; the API never accepts naive times."""

import re
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator

Policy = Literal["lab_only", "department", "institute_approval", "institute_open"]
ResourceType = Literal["instrument", "meeting_room"]
ResourceStatus = Literal["active", "maintenance", "retired"]


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$")


def _email(v: str) -> str:
    """Format check only. Stricter validators reject reserved names such as .test/.local, which the demo
    and many internal mail setups use; whether an address is real is proven by the verification email."""
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("not a valid email address")
    return v


Email = Annotated[str, AfterValidator(_email)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----------------------------------------------------------------------------------------------


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: Email
    password: str = Field(min_length=10, max_length=200)
    department_id: int | None = None


class LoginIn(BaseModel):
    email: Email
    password: str = Field(max_length=200)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(BaseModel):
    email: Email


class ResetConfirmIn(TokenIn):
    password: str = Field(min_length=10, max_length=200)


class DevToken(BaseModel):
    ok: bool = True
    dev_token: str | None = None  # only populated when RELAY_DEV_EXPOSE_TOKENS=true


# ---- organization ----------------------------------------------------------------------------------------


class DepartmentIn(BaseModel):
    code: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=3, max_length=120)


class LabIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    professor_email: Email | None = None


class MemberIn(BaseModel):
    email: Email
    role: Literal["member", "professor"] = "member"


class AdminIn(BaseModel):
    email: Email


class MembershipDecisionIn(BaseModel):
    approve: bool


# ---- resources ------------------------------------------------------------------------------------------------


class RulesFields(BaseModel):
    slot_granularity_min: int | None = Field(None, ge=5, le=1440)
    min_duration_min: int | None = Field(None, ge=5, le=10080)
    max_duration_min: int | None = Field(None, ge=5, le=10080)
    open_time: time | None = None
    close_time: time | None = None
    max_advance_days: int | None = Field(None, ge=0, le=365)
    min_notice_min: int | None = Field(None, ge=0, le=10080)
    weekly_quota_min: int | None = Field(None, ge=1, le=10080)
    cancellation_cutoff_min: int | None = Field(None, ge=0, le=10080)
    requires_checkin: bool | None = None


class ResourceIn(RulesFields):
    lab_id: int
    name: str = Field(min_length=2, max_length=120)
    type: ResourceType
    access_policy: Policy
    description: str = Field("", max_length=4000)
    location: str = Field("", max_length=200)
    accepts_requests: bool = True


class ResourcePatch(RulesFields):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=4000)
    location: str | None = Field(None, max_length=200)
    access_policy: Policy | None = None
    accepts_requests: bool | None = None
    status: ResourceStatus | None = None
    clear_weekly_quota: bool = False


class ResourceOut(Out):
    id: int
    name: str
    type: ResourceType
    description: str
    location: str
    access_policy: Policy
    accepts_requests: bool
    status: ResourceStatus
    lab_id: int
    lab_name: str
    department_id: int
    department_code: str
    department_name: str
    slot_granularity_min: int
    min_duration_min: int
    max_duration_min: int
    open_time: time
    close_time: time
    max_advance_days: int
    min_notice_min: int
    weekly_quota_min: int | None
    cancellation_cutoff_min: int
    requires_checkin: bool
    my_access: Literal["allowed", "request_pending", "request_possible", "denied"]
    can_manage: bool
    timezone: str


class MaintenanceIn(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    reason: str = Field(min_length=3, max_length=500)
    cancel_conflicts: bool = False


# ---- bookings -------------------------------------------------------------------------------------------------


class BookingIn(BaseModel):
    resource_id: int
    start: AwareDatetime
    end: AwareDatetime
    purpose: str = Field("", max_length=500)


class RescheduleIn(BaseModel):
    start: AwareDatetime
    end: AwareDatetime


class CancelIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


class BookingOut(Out):
    id: int
    resource_id: int
    resource_name: str
    lab_name: str
    kind: str
    status: str
    start: datetime
    end: datetime
    purpose: str
    series_id: int | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    late_cancel_after: datetime


class CalendarEntry(BaseModel):
    id: int | None
    start: datetime
    end: datetime
    kind: str
    status: str
    label: str
    mine: bool
    user_name: str | None
    purpose: str | None
    series_id: int | None


class QuotaOut(BaseModel):
    weekly_quota_min: int | None
    used_min: int
    remaining_min: int | None
    week_start: date


# ---- access workflow ------------------------------------------------------------------------------------------


class AccessRequestIn(BaseModel):
    justification: str = Field(min_length=20, max_length=2000)
    requested_until: date
    supervisor_name: str | None = Field(None, max_length=120)

    @field_validator("justification")
    @classmethod
    def _strip(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("at least 20 characters")
        return v.strip()


class ApproveIn(BaseModel):
    until: date | None = None
    note: str | None = Field(None, max_length=1000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class RevokeIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class AccessRequestOut(BaseModel):
    id: int
    resource_id: int
    resource_name: str
    lab_name: str
    department_code: str
    requester_id: int
    requester_name: str
    requester_email: str | None
    requester_departments: list[dict] = []
    justification: str
    requested_until: date
    supervisor_name: str | None
    status: str
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class GrantOut(BaseModel):
    id: int
    resource_id: int
    resource_name: str
    lab_name: str
    user_id: int
    user_name: str
    expires_at: datetime
    revoked_at: datetime | None
    state: Literal["active", "expired", "revoked"]
    created_at: datetime


# ---- waitlist / notifications ----------------------------------------------------------------------------------


class WaitlistIn(BaseModel):
    resource_id: int
    start: AwareDatetime
    end: AwareDatetime


class WaitlistOut(BaseModel):
    id: int
    resource_id: int
    resource_name: str
    start: datetime
    end: datetime
    status: str
    offer_expires_at: datetime | None


class NotificationOut(Out):
    id: int
    type: str
    payload: dict
    read_at: datetime | None
    created_at: datetime
