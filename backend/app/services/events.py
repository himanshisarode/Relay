"""Audit log and notifications. Both are written in the caller's transaction, so a state change and its
record commit or roll back together. Email delivery happens later in the worker (notifications are the outbox)."""

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, Notification


def audit(db: Session, actor_id: int | None, action: str, entity_type: str, entity_id: int | None, **details) -> None:
    db.add(
        AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details=_jsonable(details))
    )


def notify(
    db: Session,
    user_ids: int | Iterable[int],
    type_: str,
    *,
    title: str,
    body: str = "",
    link: str | None = None,
    email: bool = True,
    **extra,
) -> None:
    ids = [user_ids] if isinstance(user_ids, int) else sorted(set(user_ids))
    payload = {"title": title, "body": body, "link": link, **_jsonable(extra)}
    for uid in ids:
        # email=False marks the row as already "emailed" so the outbox skips it (in-app only).
        db.add(Notification(user_id=uid, type=type_, payload=payload, emailed_at=None if email else func.now()))


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out
