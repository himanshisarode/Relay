from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app import schemas
from app.api.v1 import serialize
from app.auth.deps import current_user
from app.db import get_db
from app.models import User
from app.services import bookings as bk
from app.services import resources as res
from app.services import rules
from app.settings import get_settings

router = APIRouter(tags=["resources & bookings"])


# ---- resources -----------------------------------------------------------------------------------------


@router.get("/resources", response_model=list[schemas.ResourceOut])
def list_resources(
    q: str | None = None,
    department_id: int | None = None,
    lab_id: int | None = None,
    type: schemas.ResourceType | None = None,
    bookable: bool = False,
    managed: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = res.directory(
        db, user, q=q, department_id=department_id, lab_id=lab_id, type_=type, bookable=bookable, managed=managed
    )
    return [serialize.resource(r, a, m) for r, a, m in rows]


@router.get("/resources/{resource_id}", response_model=schemas.ResourceOut)
def get_resource(resource_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.resource(*res.detail(db, user, resource_id))


@router.post("/resources", status_code=201, response_model=schemas.ResourceOut)
def create_resource(body: schemas.ResourceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"lab_id"})
    r = res.create(db, user, body.lab_id, data)
    return serialize.resource(*res.detail(db, user, r.id))


@router.patch("/resources/{resource_id}", response_model=schemas.ResourceOut)
def update_resource(
    resource_id: int, body: schemas.ResourcePatch, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    changes = body.model_dump(exclude_unset=True, exclude={"clear_weekly_quota"})
    changes = {k: v for k, v in changes.items() if v is not None}
    if body.clear_weekly_quota:
        changes["weekly_quota_min"] = None
    res.update(db, user, resource_id, changes)
    return serialize.resource(*res.detail(db, user, resource_id))


@router.post("/resources/{resource_id}/maintenance", status_code=201)
def maintenance(
    resource_id: int, body: schemas.MaintenanceIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    block, cancelled = bk.create_maintenance(db, user, resource_id, body.start, body.end, body.reason, body.cancel_conflicts)
    return {"id": block.id, "cancelled_booking_ids": [b.id for b in cancelled]}


@router.get("/resources/{resource_id}/availability", response_model=list[schemas.CalendarEntry])
def availability(
    resource_id: int,
    from_: AwareDatetime = Query(alias="from"),
    to: AwareDatetime = Query(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    r = bk.get_resource(db, resource_id)
    return bk.availability(db, user, r, from_, to)


@router.get("/resources/{resource_id}/my-quota", response_model=schemas.QuotaOut)
def my_quota(
    resource_id: int, at: AwareDatetime | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    r = bk.get_resource(db, resource_id)
    week = rules.week_start(at or bk.utcnow(), get_settings().tz).date()
    used = bk.used_minutes(db, user.id, r.id, week)
    quota = None if r.type == "meeting_room" else r.weekly_quota_min
    return schemas.QuotaOut(
        weekly_quota_min=quota, used_min=used, remaining_min=None if quota is None else max(0, quota - used), week_start=week
    )


# ---- bookings ---------------------------------------------------------------------------------------------


@router.post("/bookings", status_code=201, response_model=schemas.BookingOut)
def create_booking(body: schemas.BookingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.booking(bk.create_booking(db, user, body.resource_id, body.start, body.end, body.purpose))


@router.get("/bookings", response_model=list[schemas.BookingOut])
def list_bookings(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    include_cancelled: bool = True,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Regular users only ever see their own bookings here (spec 8); managers use the calendar and reports.
    return [serialize.booking(b) for b in bk.my_bookings(db, user, from_, to, include_cancelled)]


@router.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(
    booking_id: int, body: schemas.CancelIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return serialize.booking(bk.cancel_booking(db, user, booking_id, body.reason if body else None))


@router.post("/bookings/{booking_id}/reschedule", response_model=schemas.BookingOut)
def reschedule(
    booking_id: int, body: schemas.RescheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return serialize.booking(bk.reschedule(db, user, booking_id, body.start, body.end))
