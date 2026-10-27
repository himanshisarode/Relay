from datetime import timedelta

from app import schemas
from app.models import AccessGrant, AccessRequest, Booking, Resource
from app.services.bookings import utcnow
from app.settings import get_settings


def resource(r: Resource, access: str, manages: bool) -> schemas.ResourceOut:
    return schemas.ResourceOut(
        **{
            f: getattr(r, f)
            for f in schemas.ResourceOut.model_fields
            if f
            not in {"lab_name", "department_id", "department_code", "department_name", "my_access", "can_manage", "timezone"}
        },
        lab_name=r.lab.name,
        department_id=r.lab.department_id,
        department_code=r.lab.department.code,
        department_name=r.lab.department.name,
        my_access=access,
        can_manage=manages,
        timezone=get_settings().timezone,
    )


def booking(b: Booking) -> schemas.BookingOut:
    return schemas.BookingOut(
        id=b.id,
        resource_id=b.resource_id,
        resource_name=b.resource.name,
        lab_name=b.resource.lab.name,
        kind=b.kind,
        status=b.status,
        start=b.start,
        end=b.end,
        purpose=b.purpose,
        series_id=b.series_id,
        cancelled_at=b.cancelled_at,
        cancel_reason=b.cancel_reason,
        created_at=b.created_at,
        late_cancel_after=b.start - timedelta(minutes=b.resource.cancellation_cutoff_min),
    )


def access_request(r: AccessRequest, *, show_email: bool = False, depts: dict | None = None) -> schemas.AccessRequestOut:
    return schemas.AccessRequestOut(
        id=r.id,
        resource_id=r.resource_id,
        resource_name=r.resource.name,
        lab_name=r.resource.lab.name,
        department_code=r.resource.lab.department.code,
        requester_id=r.requester_id,
        requester_name=r.requester.name,
        requester_email=r.requester.email if show_email else None,
        requester_departments=(depts or {}).get(r.requester_id, []),
        justification=r.justification,
        requested_until=r.requested_until,
        supervisor_name=r.supervisor_name,
        status=r.status,
        decision_note=r.decision_note,
        decided_at=r.decided_at,
        created_at=r.created_at,
    )


def grant(g: AccessGrant) -> schemas.GrantOut:
    state = "revoked" if g.revoked_at else ("expired" if g.expires_at <= utcnow() else "active")
    return schemas.GrantOut(
        id=g.id,
        resource_id=g.resource_id,
        resource_name=g.resource.name,
        lab_name=g.resource.lab.name,
        user_id=g.user_id,
        user_name=g.user.name,
        expires_at=g.expires_at,
        revoked_at=g.revoked_at,
        state=state,
        created_at=g.created_at,
    )
