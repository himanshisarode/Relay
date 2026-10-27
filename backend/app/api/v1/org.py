from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.auth.deps import current_user
from app.db import get_db
from app.models import User
from app.services import org

router = APIRouter(tags=["organization"])


# Public: the registration form needs the department list.
@router.get("/departments")
def departments(db: Session = Depends(get_db)):
    return org.departments(db)


@router.get("/departments/{department_id}/labs")
def department_labs(department_id: int, db: Session = Depends(get_db)):
    return org.labs(db, department_id)


@router.get("/labs")
def all_labs(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return org.labs(db)


@router.post("/departments", status_code=201)
def create_department(body: schemas.DepartmentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = org.create_department(db, user, body.code, body.name)
    return {"id": d.id, "code": d.code, "name": d.name}


@router.put("/departments/{department_id}/admins")
def set_admin(department_id: int, body: schemas.AdminIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org.set_dept_admin(db, user, department_id, body.email)
    return {"ok": True}


@router.post("/departments/{department_id}/labs", status_code=201)
def create_lab(department_id: int, body: schemas.LabIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lab = org.create_lab(db, user, department_id, body.name, body.professor_email)
    return {"id": lab.id, "name": lab.name, "department_id": lab.department_id}


@router.get("/departments/verification-queue")
def verification_queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return org.verification_queue(db, user)


@router.post("/departments/{department_id}/members/{user_id}/verify")
def verify_member(
    department_id: int,
    user_id: int,
    body: schemas.MembershipDecisionIn | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    org.decide_membership(db, user, department_id, user_id, approve=body.approve if body else True)
    return {"ok": True}


@router.get("/labs/{lab_id}/members")
def lab_members(lab_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return org.lab_members(db, user, lab_id)


@router.post("/labs/{lab_id}/members", status_code=201)
def add_member(lab_id: int, body: schemas.MemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org.add_lab_member(db, user, lab_id, body.email, body.role)
    return {"ok": True}


@router.delete("/labs/{lab_id}/members/{user_id}")
def remove_member(lab_id: int, user_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org.remove_lab_member(db, user, lab_id, user_id)
    return {"ok": True}
