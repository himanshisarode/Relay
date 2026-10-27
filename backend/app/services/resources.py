"""Resource directory and settings. Resources belong to a lab; the lab's professor manages them."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.models import Lab, Resource, User
from app.services import org, permissions
from app.services.bookings import get_resource
from app.services.events import audit

EDITABLE = {
    "name",
    "description",
    "location",
    "access_policy",
    "accepts_requests",
    "status",
    "slot_granularity_min",
    "min_duration_min",
    "max_duration_min",
    "open_time",
    "close_time",
    "max_advance_days",
    "min_notice_min",
    "weekly_quota_min",
    "cancellation_cutoff_min",
    "requires_checkin",
}

TYPE_DEFAULTS = {
    "instrument": {"weekly_quota_min": 600},
    "meeting_room": {"weekly_quota_min": None, "max_duration_min": 180, "min_notice_min": 0, "max_advance_days": 60},
}


def directory(
    db: Session,
    user: User,
    *,
    q: str | None = None,
    department_id: int | None = None,
    lab_id: int | None = None,
    type_: str | None = None,
    bookable: bool = False,
    managed: bool = False,
) -> list[tuple[Resource, str, bool]]:
    stmt = select(Resource).join(Lab, Lab.id == Resource.lab_id).where(Resource.status != "retired")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Resource.name.ilike(like),
                Resource.description.ilike(like),
                Lab.name.ilike(like),
                Resource.location.ilike(like),
            )
        )
    if department_id:
        stmt = stmt.where(Lab.department_id == department_id)
    if lab_id:
        stmt = stmt.where(Resource.lab_id == lab_id)
    if type_:
        stmt = stmt.where(Resource.type == type_)
    facts = permissions.load_facts(db, user)
    pending = permissions.pending_request_ids(db, user)
    out = []
    for r in db.scalars(stmt.order_by(Lab.name, Resource.name)):
        access = permissions.my_access(db, facts, r, pending)
        manages = permissions.can_manage(facts, permissions.ResourceFacts.of(r))
        if bookable and access != "allowed":
            continue
        if managed and not manages:
            continue
        out.append((r, access, manages))
    return out


def detail(db: Session, user: User, resource_id: int) -> tuple[Resource, str, bool]:
    r = get_resource(db, resource_id)
    if r.status == "retired":
        org.require_lab_head(db, user, r.lab)
    facts = permissions.load_facts(db, user)
    access = permissions.my_access(db, facts, r, permissions.pending_request_ids(db, user))
    return r, access, permissions.can_manage(facts, permissions.ResourceFacts.of(r))


def create(db: Session, actor: User, lab_id: int, data: dict) -> Resource:
    lab = db.get(Lab, lab_id)
    if lab is None:
        raise NotFound("Lab not found.")
    org.require_lab_head(db, actor, lab)
    fields = {**TYPE_DEFAULTS.get(data["type"], {}), **{k: v for k, v in data.items() if v is not None}}
    r = Resource(lab_id=lab.id, **fields)
    _save(db, r)
    audit(db, actor.id, "resource.create", "resource", r.id, name=r.name)
    db.commit()
    return r


def update(db: Session, actor: User, resource_id: int, changes: dict) -> Resource:
    r = get_resource(db, resource_id, lock=True)
    permissions.require_manage(db, actor, r)
    before = {k: _plain(getattr(r, k)) for k in changes if k in EDITABLE}
    for k, v in changes.items():
        if k in EDITABLE:
            setattr(r, k, v)
    _save(db, r)
    audit(db, actor.id, "resource.update", "resource", r.id, before=before, after={k: _plain(getattr(r, k)) for k in before})
    db.commit()
    return r


def _save(db: Session, r: Resource) -> None:
    if r.max_duration_min is not None and r.min_duration_min is not None and r.max_duration_min < r.min_duration_min:
        raise Conflict("Maximum duration must be at least the minimum.", code="invalid_rules")
    try:
        with db.begin_nested():
            db.add(r)
            db.flush()
    except IntegrityError:
        raise Conflict(
            "This lab already has a resource with that name, or a rule value is invalid.", code="invalid_resource"
        ) from None


def _plain(v):
    return v.isoformat() if hasattr(v, "isoformat") else v
