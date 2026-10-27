"""Access request workflow (spec 4): pending -> approved | rejected | cancelled | expired; grants expire or are revoked."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, NotFound, RuleViolation
from app.models import (
    AccessGrant,
    AccessRequest,
    Booking,
    Department,
    DepartmentMember,
    Lab,
    LabMember,
    Resource,
    User,
)
from app.services import bookings as bk
from app.services import permissions
from app.services.events import audit, notify
from app.settings import get_settings

MAX_GRANT_DAYS = 366


def deciders(db: Session, resource: Resource) -> set[int]:
    """Professors of the owning lab and admins of the owning department; super admins only as a fallback."""
    profs = db.scalars(select(LabMember.user_id).where(LabMember.lab_id == resource.lab_id, LabMember.role == "professor"))
    admins = db.scalars(
        select(DepartmentMember.user_id).where(
            DepartmentMember.department_id == resource.lab.department_id,
            DepartmentMember.role == "dept_admin",
            DepartmentMember.verified.is_(True),
        )
    )
    ids = set(profs) | set(admins)
    if not ids:
        ids = set(db.scalars(select(User.id).where(User.is_superadmin.is_(True), User.is_active.is_(True))))
    return ids


def end_of_day(d: date) -> datetime:
    """Grants run to the end of the chosen local day."""
    return datetime.combine(d + timedelta(days=1), time(0), get_settings().tz)


def today() -> date:
    return bk.utcnow().astimezone(get_settings().tz).date()


def create_request(
    db: Session, user: User, resource_id: int, justification: str, requested_until: date, supervisor_name: str | None
) -> AccessRequest:
    resource = bk.get_resource(db, resource_id)
    if resource.status == "retired":
        raise NotFound("Resource not found.")
    if not user.email_verified:
        raise Forbidden("Verify your email address before requesting access.")
    decision = permissions.can_book(db, user, resource)
    if decision.via == "grant":
        raise Conflict("You already have access to this resource.", code="already_granted")
    if decision.allowed:
        raise Conflict("You can already book this resource.", code="already_allowed")
    if not resource.accepts_requests:
        raise Forbidden("This resource is not accepting access requests.", can_request_access=False)
    justification = justification.strip()
    if len(justification) < 20:
        raise RuleViolation("Explain why you need access (at least 20 characters).", rule="justification")
    if not today() < requested_until <= today() + timedelta(days=MAX_GRANT_DAYS):
        raise RuleViolation("Pick an end date between tomorrow and one year from now.", rule="requested_until")
    req = AccessRequest(
        resource_id=resource.id,
        requester_id=user.id,
        justification=justification,
        requested_until=requested_until,
        supervisor_name=(supervisor_name or "").strip() or None,
    )
    try:
        with db.begin_nested():
            db.add(req)
            db.flush()
    except IntegrityError:
        raise Conflict("You already have a pending request for this resource.", code="request_pending") from None
    audit(db, user.id, "access_request.create", "access_request", req.id, resource_id=resource.id)
    notify(
        db,
        deciders(db, resource) - {user.id},
        "access_request_submitted",
        title=f"{user.name} requested access to {resource.name}",
        body=justification[:280],
        link="/inbox",
        request_id=req.id,
    )
    db.commit()
    return req


def _get_request(db: Session, request_id: int) -> AccessRequest:
    r = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update(of=AccessRequest))
    if r is None:
        raise NotFound("Request not found.")
    return r


def _require_decider(db: Session, actor: User, req: AccessRequest) -> None:
    facts = permissions.load_facts(db, actor)
    rf = permissions.ResourceFacts.of(req.resource)
    if req.requester_id == actor.id:
        raise Forbidden("You can't decide your own request.", code="self_decision")
    if not permissions.can_decide(facts, rf, req.requester_id):
        raise NotFound("Request not found.")


def _require_pending(req: AccessRequest) -> None:
    if req.status != "pending":
        raise Conflict(f"This request is already {req.status}.", code="not_pending")


def approve(db: Session, actor: User, request_id: int, until: date | None, note: str | None) -> AccessGrant:
    req = _get_request(db, request_id)
    _require_decider(db, actor, req)
    _require_pending(req)
    until = until or req.requested_until
    if until > req.requested_until:
        raise RuleViolation("You can shorten the requested duration, not extend it.", rule="until_too_late")
    if until <= today() - timedelta(days=1):
        raise RuleViolation("The end date must be today or later.", rule="until_in_past")
    now = bk.utcnow()
    req.status, req.decided_by, req.decided_at = "approved", actor.id, now
    req.decision_note = (note or "").strip() or None
    grant = AccessGrant(
        resource_id=req.resource_id,
        user_id=req.requester_id,
        request_id=req.id,
        granted_by=actor.id,
        expires_at=end_of_day(until),
    )
    db.add(grant)
    db.flush()
    audit(db, actor.id, "access_request.approve", "access_request", req.id, grant_id=grant.id, until=until)
    notify(
        db,
        req.requester_id,
        "access_request_approved",
        title=f"Access to {req.resource.name} approved",
        body=f"You can book it until {until:%d %b %Y}." + (f" Note: {req.decision_note}" if req.decision_note else ""),
        link=f"/resources/{req.resource_id}",
        request_id=req.id,
    )
    db.commit()
    return grant


def reject(db: Session, actor: User, request_id: int, reason: str) -> AccessRequest:
    req = _get_request(db, request_id)
    _require_decider(db, actor, req)
    _require_pending(req)
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise RuleViolation("Give a short reason for the requester.", rule="reason_required")
    req.status, req.decided_by, req.decided_at, req.decision_note = "rejected", actor.id, bk.utcnow(), reason
    audit(db, actor.id, "access_request.reject", "access_request", req.id, reason=reason)
    notify(
        db,
        req.requester_id,
        "access_request_rejected",
        title=f"Access to {req.resource.name} not approved",
        body=f"Reason: {reason}",
        link="/access",
        request_id=req.id,
    )
    db.commit()
    return req


def cancel(db: Session, user: User, request_id: int) -> AccessRequest:
    req = _get_request(db, request_id)
    if req.requester_id != user.id:
        raise NotFound("Request not found.")
    _require_pending(req)
    req.status = "cancelled"
    audit(db, user.id, "access_request.cancel", "access_request", req.id)
    db.commit()
    return req


def revoke(db: Session, actor: User, grant_id: int, reason: str | None) -> tuple[AccessGrant, list[Booking]]:
    g = db.scalar(select(AccessGrant).where(AccessGrant.id == grant_id).with_for_update(of=AccessGrant))
    if g is None:
        raise NotFound("Grant not found.")
    facts = permissions.load_facts(db, actor)
    if not permissions.can_manage(facts, permissions.ResourceFacts.of(g.resource)):
        raise NotFound("Grant not found.")
    now = bk.utcnow()
    if g.revoked_at is not None or g.expires_at <= now:
        raise Conflict("This grant is no longer active.", code="not_active")
    g.revoked_at, g.revoked_by = now, actor.id
    audit(db, actor.id, "access_grant.revoke", "access_grant", g.id, reason=reason)
    # AC-R5: future bookings made under this grant are cancelled and their owner notified.
    future = db.scalars(
        select(Booking)
        .where(
            Booking.grant_id == g.id,
            Booking.status.in_(bk.ACTIVE),
            func.lower(Booking.during) > now,
        )
        .with_for_update(of=Booking)
    ).all()
    cancelled = []
    for b in future:
        bk.cancel_booking_tx(db, actor, b, "Access revoked", now=now, notify_owner=False, system=True)
        cancelled.append(b)
    notify(
        db,
        g.user_id,
        "access_revoked",
        title=f"Your access to {g.resource.name} was revoked",
        body=(f"Reason: {reason}. " if reason else "")
        + (f"{len(cancelled)} upcoming booking(s) were cancelled." if cancelled else ""),
        link="/access",
        grant_id=g.id,
        cancelled_booking_ids=[b.id for b in cancelled],
    )
    db.commit()
    return g, cancelled


# ---- listings ------------------------------------------------------------------------------------------------


def my_requests(db: Session, user: User) -> list[AccessRequest]:
    return list(
        db.scalars(
            select(AccessRequest).where(AccessRequest.requester_id == user.id).order_by(AccessRequest.created_at.desc())
        )
    )


def my_grants(db: Session, user: User) -> list[AccessGrant]:
    return list(
        db.scalars(select(AccessGrant).where(AccessGrant.user_id == user.id).order_by(AccessGrant.expires_at.desc()))
    )


def to_decide(db: Session, user: User, status: str = "pending") -> list[AccessRequest]:
    facts = permissions.load_facts(db, user)
    stmt = (
        select(AccessRequest)
        .join(Resource, Resource.id == AccessRequest.resource_id)
        .join(Lab, Lab.id == Resource.lab_id)
        .where(AccessRequest.status == status, AccessRequest.requester_id != user.id)
    )
    if not facts.is_superadmin:
        stmt = stmt.where(or_(Lab.id.in_(facts.professor_lab_ids), Lab.department_id.in_(facts.admin_department_ids)))
    return list(db.scalars(stmt.order_by(AccessRequest.created_at)))


def grants_for_manager(db: Session, user: User) -> list[AccessGrant]:
    facts = permissions.load_facts(db, user)
    stmt = (
        select(AccessGrant)
        .join(Resource, Resource.id == AccessGrant.resource_id)
        .join(Lab, Lab.id == Resource.lab_id)
        .where(AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > bk.utcnow())
    )
    if not facts.is_superadmin:
        stmt = stmt.where(or_(Lab.id.in_(facts.professor_lab_ids), Lab.department_id.in_(facts.admin_department_ids)))
    return list(db.scalars(stmt.order_by(AccessGrant.expires_at)))


def requester_departments(db: Session, user_ids: set[int]) -> dict[int, list[dict]]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(DepartmentMember.user_id, Department.code, Department.name, DepartmentMember.verified)
        .join(Department, Department.id == DepartmentMember.department_id)
        .where(DepartmentMember.user_id.in_(user_ids))
    ).all()
    out: dict[int, list[dict]] = {}
    for uid, code, name, verified in rows:
        out.setdefault(uid, []).append({"code": code, "name": name, "verified": verified})
    return out


# ---- worker jobs (idempotent) -----------------------------------------------------------------------------------


def expire_stale_requests(db: Session, now: datetime | None = None) -> int:
    now = now or bk.utcnow()
    cutoff = now - timedelta(days=get_settings().access_request_expiry_days)
    stale = db.scalars(
        select(AccessRequest)
        .where(AccessRequest.status == "pending", AccessRequest.created_at < cutoff)
        .with_for_update(of=AccessRequest, skip_locked=True)
    ).all()
    for r in stale:
        r.status = "expired"
        audit(db, None, "access_request.expire", "access_request", r.id)
        notify(
            db,
            r.requester_id,
            "access_request_expired",
            title=f"Your request for {r.resource.name} expired",
            body="Nobody decided it within 30 days. You can send a new request.",
            link="/access",
            request_id=r.id,
        )
    db.commit()
    return len(stale)


def warn_expiring_grants(db: Session, now: datetime | None = None) -> int:
    now = now or bk.utcnow()
    soon = db.scalars(
        select(AccessGrant)
        .where(
            AccessGrant.revoked_at.is_(None),
            AccessGrant.expiry_warned_at.is_(None),
            AccessGrant.expires_at > now,
            AccessGrant.expires_at <= now + timedelta(days=7),
        )
        .with_for_update(of=AccessGrant, skip_locked=True)
    ).all()
    for g in soon:
        g.expiry_warned_at = now
        notify(
            db,
            g.user_id,
            "grant_expiring",
            title=f"Your access to {g.resource.name} ends soon",
            body=f"It expires on {bk.fmt(g.expires_at)}. Send a new request if you still need it.",
            link=f"/resources/{g.resource_id}",
            grant_id=g.id,
        )
    db.commit()
    return len(soon)
