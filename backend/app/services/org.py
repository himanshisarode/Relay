"""Departments, labs and memberships. Super admins create departments and appoint department admins;
department admins create labs, appoint professors and verify members; professors run their own lab."""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, NotFound
from app.models import Department, DepartmentMember, Lab, LabMember, Resource, User
from app.services import permissions
from app.services.bookings import utcnow
from app.services.events import audit, notify


def _user_by_email(db: Session, email: str) -> User:
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if u is None:
        raise NotFound("No account with that email. Ask them to register first.")
    return u


def _department(db: Session, department_id: int) -> Department:
    d = db.get(Department, department_id)
    if d is None:
        raise NotFound("Department not found.")
    return d


def _lab(db: Session, lab_id: int) -> Lab:
    lab = db.get(Lab, lab_id)
    if lab is None:
        raise NotFound("Lab not found.")
    return lab


def require_superadmin(user: User) -> None:
    if not user.is_superadmin:
        raise Forbidden("Only a super admin can do this.")


def require_dept_admin(db: Session, user: User, department_id: int) -> None:
    f = permissions.load_facts(db, user)
    if not (f.is_superadmin or department_id in f.admin_department_ids):
        raise Forbidden("Only this department's admin can do this.")


def require_lab_head(db: Session, user: User, lab: Lab) -> None:
    """The professor of the lab has whole access over it; dept admins and super admins can act too."""
    f = permissions.load_facts(db, user)
    if not (f.is_superadmin or lab.id in f.professor_lab_ids or lab.department_id in f.admin_department_ids):
        raise Forbidden("Only the lab's professor or a department admin can do this.")


# ---- reads -----------------------------------------------------------------------------------------------


def departments(db: Session) -> list[dict]:
    rows = db.execute(
        select(Department, func.count(Lab.id))
        .outerjoin(Lab, Lab.department_id == Department.id)
        .group_by(Department.id)
        .order_by(Department.name)
    ).all()
    return [{"id": d.id, "code": d.code, "name": d.name, "lab_count": n} for d, n in rows]


def labs(db: Session, department_id: int | None = None) -> list[dict]:
    prof = (
        select(LabMember.lab_id, func.string_agg(User.name, ", ").label("professors"))
        .join(User, User.id == LabMember.user_id)
        .where(LabMember.role == "professor")
        .group_by(LabMember.lab_id)
        .subquery()
    )
    counts = (
        select(Resource.lab_id, func.count().label("n"))
        .where(Resource.status != "retired")
        .group_by(Resource.lab_id)
        .subquery()
    )
    stmt = (
        select(Lab, prof.c.professors, func.coalesce(counts.c.n, 0))
        .outerjoin(prof, prof.c.lab_id == Lab.id)
        .outerjoin(counts, counts.c.lab_id == Lab.id)
        .order_by(Lab.name)
    )
    if department_id is not None:
        stmt = stmt.where(Lab.department_id == department_id)
    return [
        {
            "id": lab.id,
            "name": lab.name,
            "department_id": lab.department_id,
            "department_code": lab.department.code,
            "department_name": lab.department.name,
            "professors": profs or "",
            "resource_count": n,
        }
        for lab, profs, n in db.execute(stmt).all()
    ]


def lab_members(db: Session, viewer: User, lab_id: int) -> list[dict]:
    lab = _lab(db, lab_id)
    require_lab_head(db, viewer, lab)
    rows = db.execute(
        select(LabMember, User)
        .join(User, User.id == LabMember.user_id)
        .where(LabMember.lab_id == lab_id)
        .order_by(LabMember.role.desc(), User.name)
    ).all()
    return [{"user_id": u.id, "name": u.name, "email": u.email, "role": m.role, "since": m.created_at} for m, u in rows]


def me(db: Session, user: User) -> dict:
    labs_ = db.execute(
        select(LabMember.role, Lab)
        .join(Lab, Lab.id == LabMember.lab_id)
        .where(LabMember.user_id == user.id)
        .order_by(Lab.name)
    ).all()
    depts = db.execute(
        select(DepartmentMember, Department)
        .join(Department, Department.id == DepartmentMember.department_id)
        .where(DepartmentMember.user_id == user.id)
    ).all()
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "email_verified": user.email_verified,
        "is_superadmin": user.is_superadmin,
        "labs": [
            {"id": lab.id, "name": lab.name, "role": role, "department_code": lab.department.code} for role, lab in labs_
        ],
        "departments": [
            {"id": d.id, "code": d.code, "name": d.name, "role": m.role, "verified": m.verified} for m, d in depts
        ],
        "is_professor": any(r == "professor" for r, _ in labs_),
        "is_dept_admin": any(m.role == "dept_admin" and m.verified for m, _ in depts),
    }


# ---- writes ----------------------------------------------------------------------------------------------


def create_department(db: Session, actor: User, code: str, name: str) -> Department:
    require_superadmin(actor)
    d = Department(code=code.strip().upper(), name=name.strip())
    try:
        with db.begin_nested():
            db.add(d)
            db.flush()
    except IntegrityError:
        raise Conflict("A department with that code or name already exists.", code="duplicate") from None
    audit(db, actor.id, "department.create", "department", d.id, code=d.code)
    db.commit()
    return d


def set_dept_admin(db: Session, actor: User, department_id: int, email: str) -> None:
    require_superadmin(actor)
    _department(db, department_id)
    u = _user_by_email(db, email)
    m = db.get(DepartmentMember, (u.id, department_id))
    if m is None:
        m = DepartmentMember(user_id=u.id, department_id=department_id)
        db.add(m)
    m.role, m.verified, m.verified_by, m.verified_at = "dept_admin", True, actor.id, utcnow()
    audit(db, actor.id, "department.admin_set", "department", department_id, user_id=u.id)
    notify(db, u.id, "role_granted", title="You are now a department admin", link="/admin")
    db.commit()


def create_lab(db: Session, actor: User, department_id: int, name: str, professor_email: str | None) -> Lab:
    require_dept_admin(db, actor, department_id)
    lab = Lab(department_id=department_id, name=name.strip())
    try:
        with db.begin_nested():
            db.add(lab)
            db.flush()
    except IntegrityError:
        raise Conflict("This department already has a lab with that name.", code="duplicate") from None
    audit(db, actor.id, "lab.create", "lab", lab.id, name=lab.name)
    if professor_email:
        _put_member(db, actor, lab, _user_by_email(db, professor_email), "professor")
    db.commit()
    return lab


def add_lab_member(db: Session, actor: User, lab_id: int, email: str, role: str) -> None:
    lab = _lab(db, lab_id)
    if role == "professor":
        require_dept_admin(db, actor, lab.department_id)  # appointing a lab head is the department's call
    else:
        require_lab_head(db, actor, lab)
    _put_member(db, actor, lab, _user_by_email(db, email), role)
    db.commit()


def _put_member(db: Session, actor: User, lab: Lab, u: User, role: str) -> None:
    m = db.get(LabMember, (u.id, lab.id))
    if m is None:
        db.add(LabMember(user_id=u.id, lab_id=lab.id, role=role, added_by=actor.id))
    else:
        m.role = role
    # Being added to a lab by its professor vouches for the department too.
    dm = db.get(DepartmentMember, (u.id, lab.department_id))
    if dm is None:
        db.add(
            DepartmentMember(
                user_id=u.id, department_id=lab.department_id, verified=True, verified_by=actor.id, verified_at=utcnow()
            )
        )
    elif not dm.verified:
        dm.verified, dm.verified_by, dm.verified_at = True, actor.id, utcnow()
    audit(db, actor.id, "lab.member_set", "lab", lab.id, user_id=u.id, role=role)
    notify(
        db,
        u.id,
        "lab_membership",
        title=f"You were added to {lab.name}" + (" as professor" if role == "professor" else ""),
        link="/resources?mine=1",
        email=False,
    )


def remove_lab_member(db: Session, actor: User, lab_id: int, user_id: int) -> None:
    lab = _lab(db, lab_id)
    m = db.get(LabMember, (user_id, lab_id))
    if m is None:
        raise NotFound("Not a member of this lab.")
    if m.role == "professor":
        require_dept_admin(db, actor, lab.department_id)
    else:
        require_lab_head(db, actor, lab)
    db.execute(delete(LabMember).where(LabMember.user_id == user_id, LabMember.lab_id == lab_id))
    audit(db, actor.id, "lab.member_remove", "lab", lab_id, user_id=user_id)
    db.commit()


def verification_queue(db: Session, actor: User) -> list[dict]:
    f = permissions.load_facts(db, actor)
    stmt = (
        select(DepartmentMember, User, Department)
        .join(User, User.id == DepartmentMember.user_id)
        .join(Department, Department.id == DepartmentMember.department_id)
        .where(DepartmentMember.verified.is_(False))
        .order_by(DepartmentMember.created_at)
    )
    if not f.is_superadmin:
        if not f.admin_department_ids:
            raise Forbidden("Only department admins can verify members.")
        stmt = stmt.where(DepartmentMember.department_id.in_(f.admin_department_ids))
    return [
        {
            "user_id": u.id,
            "name": u.name,
            "email": u.email,
            "email_verified": u.email_verified,
            "department_id": d.id,
            "department_code": d.code,
            "requested_at": m.created_at,
        }
        for m, u, d in db.execute(stmt).all()
    ]


def decide_membership(db: Session, actor: User, department_id: int, user_id: int, approve: bool) -> None:
    require_dept_admin(db, actor, department_id)
    m = db.get(DepartmentMember, (user_id, department_id))
    if m is None:
        raise NotFound("No such membership.")
    dept = _department(db, department_id)
    if approve:
        m.verified, m.verified_by, m.verified_at = True, actor.id, utcnow()
        notify(
            db,
            user_id,
            "department_verified",
            title=f"Your membership of {dept.name} is confirmed",
            body="You can now book this department's resources.",
            link="/resources",
        )
    else:
        db.delete(m)
        notify(
            db,
            user_id,
            "department_rejected",
            title=f"Your membership of {dept.name} was not confirmed",
            body="Contact the department office if this is a mistake.",
        )
    audit(
        db,
        actor.id,
        "department.member_" + ("verify" if approve else "reject"),
        "department",
        department_id,
        user_id=user_id,
    )
    db.commit()
