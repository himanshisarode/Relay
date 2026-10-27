from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import schemas
from app.auth.deps import current_user
from app.db import get_db
from app.errors import NotFound
from app.models import Notification, Resource, User
from app.services import waitlist
from app.services.bookings import utcnow

router = APIRouter(tags=["waitlist & notifications"])


@router.post("/waitlist", status_code=201, response_model=schemas.WaitlistOut)
def join(body: schemas.WaitlistIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(db, waitlist.join(db, user, body.resource_id, body.start, body.end))


@router.get("/waitlist", response_model=list[schemas.WaitlistOut])
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(db, e) for e in waitlist.mine(db, user)]


@router.post("/waitlist/{entry_id}/accept")
def accept(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = waitlist.accept(db, user, entry_id)
    return {"booking_id": b.id}


@router.delete("/waitlist/{entry_id}")
def leave(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    waitlist.leave(db, user, entry_id)
    return {"ok": True}


def _out(db: Session, e) -> schemas.WaitlistOut:
    return schemas.WaitlistOut(
        id=e.id,
        resource_id=e.resource_id,
        resource_name=db.get(Resource, e.resource_id).name,
        start=e.desired_during.lower,
        end=e.desired_during.upper,
        status=e.status,
        offer_expires_at=e.offer_expires_at,
    )


@router.get("/notifications")
def notifications(limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(min(limit, 200))
    ).all()
    unread = db.scalar(select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    items = []
    for n in rows:
        payload = dict(n.payload)
        if n.type in ("email_verification", "password_reset"):
            payload.pop("link", None)  # token links only go out by email
        items.append(
            schemas.NotificationOut(id=n.id, type=n.type, payload=payload, read_at=n.read_at, created_at=n.created_at)
        )
    return {"unread": unread, "items": items}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise NotFound("Notification not found.")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    )
    db.commit()
    return {"ok": True}
