from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.api.v1 import serialize
from app.auth.deps import current_user
from app.db import get_db
from app.errors import RuleViolation
from app.models import User
from app.services import access

router = APIRouter(tags=["access workflow"])


@router.post("/resources/{resource_id}/access-requests", status_code=201, response_model=schemas.AccessRequestOut)
def create_request(
    resource_id: int, body: schemas.AccessRequestIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    r = access.create_request(db, user, resource_id, body.justification, body.requested_until, body.supervisor_name)
    return serialize.access_request(r)


@router.get("/access-requests", response_model=list[schemas.AccessRequestOut])
def list_requests(
    mine: bool = False,
    to_decide: bool = False,
    status: str = "pending",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if mine == to_decide:
        raise RuleViolation("Pass exactly one of mine=true or to_decide=true.", rule="filter")
    if mine:
        return [serialize.access_request(r) for r in access.my_requests(db, user)]
    rows = access.to_decide(db, user, status)
    depts = access.requester_departments(db, {r.requester_id for r in rows})
    return [serialize.access_request(r, show_email=True, depts=depts) for r in rows]


@router.post("/access-requests/{request_id}/approve", response_model=schemas.GrantOut)
def approve(request_id: int, body: schemas.ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.grant(access.approve(db, user, request_id, body.until, body.note))


@router.post("/access-requests/{request_id}/reject", response_model=schemas.AccessRequestOut)
def reject(request_id: int, body: schemas.RejectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.access_request(access.reject(db, user, request_id, body.reason))


@router.post("/access-requests/{request_id}/cancel", response_model=schemas.AccessRequestOut)
def cancel(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.access_request(access.cancel(db, user, request_id))


@router.get("/access-grants", response_model=list[schemas.GrantOut])
def list_grants(mine: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = access.my_grants(db, user) if mine else access.grants_for_manager(db, user)
    return [serialize.grant(g) for g in rows]


@router.post("/access-grants/{grant_id}/revoke")
def revoke(
    grant_id: int, body: schemas.RevokeIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    g, cancelled = access.revoke(db, user, grant_id, body.reason if body else None)
    return {"grant": serialize.grant(g), "cancelled_booking_ids": [b.id for b in cancelled]}
