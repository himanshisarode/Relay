"""Permission resolution (spec 3.2). Every endpoint that reads or writes bookings goes through this module.

`decide()` is a pure function over plain facts so the whole role x policy x grant matrix can be tested
without a database; `load_facts()` builds those facts for a user from the database.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Forbidden
from app.models import AccessGrant, AccessRequest, DepartmentMember, Lab, LabMember, Resource, User


@dataclass(frozen=True)
class ResourceFacts:
    id: int
    lab_id: int
    department_id: int
    access_policy: str
    accepts_requests: bool
    status: str

    @classmethod
    def of(cls, r: Resource) -> "ResourceFacts":
        return cls(r.id, r.lab_id, r.lab.department_id, r.access_policy, r.accepts_requests, r.status)


@dataclass(frozen=True)
class UserFacts:
    user_id: int
    is_active: bool = True
    email_verified: bool = True
    is_superadmin: bool = False
    professor_lab_ids: frozenset[int] = frozenset()
    lab_ids: frozenset[int] = frozenset()  # every lab the user belongs to, any role
    lab_department_ids: frozenset[int] = frozenset()  # departments of those labs
    verified_department_ids: frozenset[int] = frozenset()  # verified department memberships only
    admin_department_ids: frozenset[int] = frozenset()  # verified dept_admin memberships
    grants: dict[int, int] = field(default_factory=dict)  # resource_id -> active grant id


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    can_request_access: bool = False
    via: str | None = None  # privileged | grant | policy
    grant_id: int | None = None

    @property
    def privileged(self) -> bool:
        """Professors of the owning lab and admins are exempt from quota and advance limits (spec 5.2)."""
        return self.via == "privileged"


def is_privileged(u: UserFacts, r: ResourceFacts) -> bool:
    return u.is_superadmin or r.lab_id in u.professor_lab_ids or r.department_id in u.admin_department_ids


def decide(u: UserFacts, r: ResourceFacts) -> Decision:
    # Step 0: only active, email-verified accounts book anything (spec 14).
    if not u.is_active:
        return Decision(False, "account_inactive")
    if not u.email_verified:
        return Decision(False, "email_not_verified")
    # Step 1
    if r.status != "active":
        return Decision(False, "resource_unavailable")
    # Step 2
    if is_privileged(u, r):
        return Decision(True, "privileged", via="privileged")
    # Step 3
    if r.id in u.grants:
        return Decision(True, "grant", via="grant", grant_id=u.grants[r.id])
    # Step 4
    policy = r.access_policy
    if policy == "lab_only" and r.lab_id in u.lab_ids:
        return Decision(True, "lab_member", via="policy")
    if policy == "department" and (r.department_id in u.verified_department_ids or r.department_id in u.lab_department_ids):
        return Decision(True, "department_member", via="policy")
    if policy == "institute_open":
        return Decision(True, "institute_open", via="policy")
    # Step 5
    reason = {
        "lab_only": "lab_members_only",
        "department": "department_members_only",
        "institute_approval": "approval_required",
    }.get(policy, "denied")
    return Decision(False, reason, can_request_access=r.accepts_requests)


def can_manage(u: UserFacts, r: ResourceFacts) -> bool:
    """Edit the resource, set rules, block maintenance, see who booked, decide requests."""
    return u.is_active and is_privileged(u, r)


def can_decide(u: UserFacts, r: ResourceFacts, requester_id: int) -> bool:
    """A requester can never decide their own request, whatever else they manage (AC-R3)."""
    return can_manage(u, r) and u.user_id != requester_id


# ---- database loading --------------------------------------------------------------------------------


def load_facts(db: Session, user: User, now: datetime | None = None) -> UserFacts:
    now = now or datetime.now(UTC)
    lab_rows = db.execute(
        select(LabMember.lab_id, LabMember.role, Lab.department_id)
        .join(Lab, Lab.id == LabMember.lab_id)
        .where(LabMember.user_id == user.id)
    ).all()
    dept_rows = db.execute(
        select(DepartmentMember.department_id, DepartmentMember.role).where(
            DepartmentMember.user_id == user.id, DepartmentMember.verified.is_(True)
        )
    ).all()
    grant_rows = db.execute(
        select(AccessGrant.resource_id, AccessGrant.id).where(
            AccessGrant.user_id == user.id, AccessGrant.revoked_at.is_(None), AccessGrant.expires_at > now
        )
    ).all()
    return UserFacts(
        user_id=user.id,
        is_active=user.is_active,
        email_verified=user.email_verified,
        is_superadmin=user.is_superadmin,
        professor_lab_ids=frozenset(r.lab_id for r in lab_rows if r.role == "professor"),
        lab_ids=frozenset(r.lab_id for r in lab_rows),
        lab_department_ids=frozenset(r.department_id for r in lab_rows),
        verified_department_ids=frozenset(r.department_id for r in dept_rows),
        admin_department_ids=frozenset(r.department_id for r in dept_rows if r.role == "dept_admin"),
        grants={r.resource_id: r.id for r in grant_rows},
    )


def can_book(db: Session, user: User, resource: Resource) -> Decision:
    return decide(load_facts(db, user), ResourceFacts.of(resource))


def my_access(db: Session, facts: UserFacts, resource: Resource, pending_resource_ids: set[int]) -> str:
    """UI hint: allowed | request_pending | request_possible | denied."""
    d = decide(facts, ResourceFacts.of(resource))
    if d.allowed:
        return "allowed"
    if resource.id in pending_resource_ids:
        return "request_pending"
    return "request_possible" if d.can_request_access else "denied"


def pending_request_ids(db: Session, user: User) -> set[int]:
    return set(
        db.scalars(
            select(AccessRequest.resource_id).where(AccessRequest.requester_id == user.id, AccessRequest.status == "pending")
        )
    )


def require_book(db: Session, user: User, resource: Resource) -> Decision:
    d = can_book(db, user, resource)
    if not d.allowed:
        raise Forbidden(_deny_message(d.reason), reason=d.reason, can_request_access=d.can_request_access)
    return d


def require_manage(db: Session, user: User, resource: Resource) -> UserFacts:
    facts = load_facts(db, user)
    if not can_manage(facts, ResourceFacts.of(resource)):
        raise Forbidden("Only the lab's professor or an admin can do this.", can_request_access=False)
    return facts


def _deny_message(reason: str) -> str:
    return {
        "account_inactive": "This account is disabled.",
        "email_not_verified": "Verify your email address before booking.",
        "resource_unavailable": "This resource is not available for booking right now.",
        "lab_members_only": "Only members of this lab can book this resource.",
        "department_members_only": "Only verified members of this department can book this resource.",
        "approval_required": "This resource needs approved access before you can book it.",
    }.get(reason, "You don't have access to this resource.")
