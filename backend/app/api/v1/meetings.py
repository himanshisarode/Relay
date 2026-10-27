from datetime import date, time
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1 import serialize
from app.auth.deps import current_user
from app.db import get_db
from app.models import User
from app.schemas import Email
from app.services import reports, series

router = APIRouter(tags=["meetings & reports"])


class SeriesIn(BaseModel):
    resource_id: int
    title: str = Field(min_length=3, max_length=200)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    interval: Literal[1, 2] = 1
    local_start_time: time
    duration_min: int = Field(ge=15, le=480)
    starts_on: date
    ends_on: date | None = None
    count: int | None = Field(None, ge=1, le=200)
    mode: Literal["all_or_nothing", "skip_conflicts"] = "skip_conflicts"
    attendee_emails: list[Email] = Field(default_factory=list, max_length=100)


@router.post("/booking-series", status_code=201)
def create_series(body: SeriesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, made, skipped = series.create(
        db,
        user,
        body.resource_id,
        title=body.title,
        weekdays=body.weekdays,
        interval=body.interval,
        local_start_time=body.local_start_time,
        duration_min=body.duration_min,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        count=body.count,
        mode=body.mode,
        attendee_emails=[str(e) for e in body.attendee_emails],
    )
    return {"id": s.id, "rrule": s.rrule_text, "created": [serialize.booking(b) for b in made], "skipped": skipped}


@router.post("/booking-series/{series_id}/cancel")
def cancel_series(
    series_id: int,
    scope: Literal["this", "future"],
    booking_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    cancelled = series.cancel(db, user, series_id, scope, booking_id)
    return {"cancelled_booking_ids": [b.id for b in cancelled]}


def _filters(resource_id: int | None, lab_id: int | None, user_id: int | None) -> dict:
    return {"resource_id": resource_id, "lab_id": lab_id, "user_id": user_id}


@router.get("/reports/usage")
def usage(
    from_: AwareDatetime = Query(alias="from"),
    to: AwareDatetime = Query(),
    resource_id: int | None = None,
    lab_id: int | None = None,
    user_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return reports.usage(db, user, from_, to, **_filters(resource_id, lab_id, user_id))


@router.get("/reports/usage.csv")
def usage_csv(
    from_: AwareDatetime = Query(alias="from"),
    to: AwareDatetime = Query(),
    resource_id: int | None = None,
    lab_id: int | None = None,
    user_id: int | None = None,
    raw: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    f = _filters(resource_id, lab_id, user_id)
    body = reports.raw_csv(db, user, from_, to, **f) if raw else reports.usage_csv(reports.usage(db, user, from_, to, **f))
    name = f"relay-{'bookings' if raw else 'usage'}-{from_:%Y%m%d}-{to:%Y%m%d}.csv"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
