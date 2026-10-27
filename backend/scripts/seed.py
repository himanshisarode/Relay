"""Load demo data from seed/institute.yaml. Idempotent: safe to run on every `docker compose up`.

python -m scripts.seed            # departments, labs, people, resources, sample activity
python -m scripts.seed --no-demo  # organization only, no sample bookings/requests
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db import session_factory
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
from app.settings import get_settings

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "institute.yaml"
DEV_PASSWORD = "relay-demo-pass"  # every seeded account; dev and demo only
SUPERADMIN = ("Relay Super Admin", "admin@relay.test")


class Seeder:
    def __init__(self, db: Session):
        self.db = db
        self.pw = hash_password(DEV_PASSWORD)
        self.created = {"users": 0, "departments": 0, "labs": 0, "resources": 0}

    def user(self, name: str, email: str, *, verified: bool = True, superadmin: bool = False) -> User:
        u = self.db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(name=name, email=email, password_hash=self.pw, email_verified=verified, is_superadmin=superadmin)
            self.db.add(u)
            self.db.flush()
            self.created["users"] += 1
        return u

    def dept_member(self, u: User, d: Department, role: str = "member", verified: bool = True) -> None:
        m = self.db.get(DepartmentMember, (u.id, d.id))
        if m is None:
            self.db.add(
                DepartmentMember(
                    user_id=u.id,
                    department_id=d.id,
                    role=role,
                    verified=verified,
                    verified_at=datetime.now().astimezone() if verified else None,
                )
            )
        elif role == "dept_admin":
            m.role, m.verified = role, True

    def lab_member(self, u: User, lab: Lab, role: str) -> None:
        if self.db.get(LabMember, (u.id, lab.id)) is None:
            self.db.add(LabMember(user_id=u.id, lab_id=lab.id, role=role))
        self.dept_member(u, lab.department)

    def run(self, data: dict) -> None:
        self.user(*SUPERADMIN, superadmin=True)
        profiles = data["profiles"]
        for d in data["departments"]:
            dept = self.db.scalar(select(Department).where(Department.code == d["code"]))
            if dept is None:
                dept = Department(code=d["code"], name=d["name"])
                self.db.add(dept)
                self.db.flush()
                self.created["departments"] += 1
            head = d["dept_admin"]
            self.dept_member(self.user(head["name"], head["email"]), dept, "dept_admin")
            for L in d["labs"]:
                lab = self.db.scalar(select(Lab).where(Lab.department_id == dept.id, Lab.name == L["name"]))
                if lab is None:
                    lab = Lab(department_id=dept.id, name=L["name"])
                    self.db.add(lab)
                    self.db.flush()
                    self.created["labs"] += 1
                self.lab_member(self.user(L["professor"]["name"], L["professor"]["email"]), lab, "professor")
                for m in L.get("members", []):
                    self.lab_member(self.user(m["name"], m["email"]), lab, "member")
                for r in L["resources"]:
                    self.resource(lab, r, profiles[r["profile"]])
        self.db.flush()

    def resource(self, lab: Lab, r: dict, profile: dict) -> None:
        if self.db.scalar(select(Resource.id).where(Resource.lab_id == lab.id, Resource.name == r["name"])):
            return
        rules = {k: (time.fromisoformat(v) if k.endswith("_time") else v) for k, v in profile.items()}
        self.db.add(
            Resource(
                lab_id=lab.id,
                name=r["name"],
                type=r["type"],
                access_policy=r["policy"],
                location=r.get("location", ""),
                description=r.get("description", ""),
                accepts_requests=True,
                status="active",
                **rules,
            )
        )
        self.created["resources"] += 1

    # ---- sample activity so every page has something to show ---------------------------------------------

    def demo(self) -> None:
        db, tz = self.db, get_settings().tz
        if db.scalar(select(Booking.id).limit(1)):
            return  # already seeded
        res = lambda name: db.scalar(select(Resource).where(Resource.name == name))  # noqa: E731

        # Accounts that exercise the edge cases of the access model.
        guest = self.user("Guest Researcher", "guest@relay.test")  # verified, no membership
        newbie = self.user("New Student", "new.student@relay.test")  # department claim awaiting verification
        self.dept_member(newbie, db.scalar(select(Department).where(Department.code == "PHY")), verified=False)
        self.user("Unverified Email", "unverified@relay.test", verified=False)
        db.flush()

        start_day = date.today() + timedelta(days=1)
        while start_day.weekday() >= 5:
            start_day += timedelta(days=1)

        def at(day_offset: int, hh: int, mm: int = 0) -> datetime:
            return datetime.combine(start_day + timedelta(days=day_offset), time(hh, mm), tz)

        def book(user: User, resource: Resource, s: datetime, minutes: int, purpose: str, **kw) -> None:
            db.add(
                Booking(
                    resource_id=resource.id,
                    user_id=user.id,
                    kind=kw.pop("kind", "usage"),
                    during=Range(s, s + timedelta(minutes=minutes), bounds="[)"),
                    purpose=purpose,
                    **kw,
                )
            )

        # Each lab's members book a few of their lab's instruments over the next week.
        for lab in db.scalars(select(Lab).order_by(Lab.id)):
            members = db.scalars(
                select(User)
                .join(LabMember, LabMember.user_id == User.id)
                .where(LabMember.lab_id == lab.id, LabMember.role == "member")
                .order_by(User.id)
            ).all()
            instruments = db.scalars(
                select(Resource).where(Resource.lab_id == lab.id, Resource.type == "instrument").order_by(Resource.id)
            ).all()
            for i, (m, r) in enumerate(zip(members, instruments, strict=False)):
                open_h = max(r.open_time.hour, 9) if r.open_time != r.close_time else 9
                book(
                    m,
                    r,
                    at(i % 4, open_h + (i % 2) * 2),
                    max(r.min_duration_min, 60) // 30 * 30 or 60,
                    ["Sample characterisation", "Calibration run", "Thesis measurements"][i % 3],
                )
            # Past usage so reports have history.
            for j, m in enumerate(members[:2]):
                if instruments:
                    r = instruments[0]
                    for w in range(1, 4):
                        s = datetime.combine(date.today() - timedelta(days=7 * w - j), time(10), tz)
                        book(m, r, s, max(r.min_duration_min, 60), "Weekly measurement", status="completed")

        # Weekly group meeting in each lab meeting room, plus a maintenance block.
        for room in db.scalars(select(Resource).where(Resource.type == "meeting_room")):
            prof = db.scalar(
                select(User)
                .join(LabMember, LabMember.user_id == User.id)
                .where(LabMember.lab_id == room.lab_id, LabMember.role == "professor")
            )
            book(prof, room, at(2, 16), 60, "Group meeting", kind="meeting")
        sem = res("SEM (Scanning Electron Microscope)")
        if sem:
            prof = db.scalar(
                select(User)
                .join(LabMember, LabMember.user_id == User.id)
                .where(LabMember.lab_id == sem.lab_id, LabMember.role == "professor")
            )
            book(prof, sem, at(3, 8), 240, "Filament replacement", kind="maintenance")

        # Access workflow: a pending request, a granted outsider, and a rejected one.
        csa_student = db.scalar(
            select(User)
            .join(LabMember, LabMember.user_id == User.id)
            .join(Lab, Lab.id == LabMember.lab_id)
            .join(Department, Department.id == Lab.department_id)
            .where(Department.code == "CSA", LabMember.role == "member")
            .order_by(User.id)
        )
        confocal, tem, raman = (
            res("Confocal Microscope"),
            res("TEM (Transmission Electron Microscope)"),
            res("Raman Spectrometer"),
        )
        if csa_student and confocal:
            db.add(
                AccessRequest(
                    resource_id=confocal.id,
                    requester_id=csa_student.id,
                    requested_until=date.today() + timedelta(days=90),
                    justification="Imaging hydrogel samples for a joint project with the Soft Matter Lab.",
                    supervisor_name="Prof. (CSA supervisor)",
                )
            )
        if guest and tem:
            db.add(
                AccessRequest(
                    resource_id=tem.id,
                    requester_id=guest.id,
                    requested_until=date.today() + timedelta(days=30),
                    justification="Need lattice imaging of nanoparticles for a visiting collaboration.",
                )
            )
        if guest and raman:
            prof = db.scalar(
                select(User)
                .join(LabMember, LabMember.user_id == User.id)
                .where(LabMember.lab_id == raman.lab_id, LabMember.role == "professor")
            )
            req = AccessRequest(
                resource_id=raman.id,
                requester_id=guest.id,
                status="approved",
                decided_by=prof.id,
                decided_at=datetime.now(tz),
                requested_until=date.today() + timedelta(days=60),
                justification="Raman mapping of graphene films for a short visit.",
                decision_note="Please book in the afternoons.",
            )
            db.add(req)
            db.flush()
            g = AccessGrant(
                resource_id=raman.id,
                user_id=guest.id,
                request_id=req.id,
                granted_by=prof.id,
                expires_at=datetime.combine(date.today() + timedelta(days=61), time(0), tz),
            )
            db.add(g)
            db.flush()
            book(guest, raman, at(1, 14), 120, "Graphene Raman maps", grant_id=g.id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-demo", action="store_true")
    ap.add_argument("--file", default=str(SEED_FILE))
    args = ap.parse_args()
    data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    with session_factory()() as db:
        s = Seeder(db)
        s.run(data)
        if not args.no_demo:
            s.demo()
        db.commit()
    print(f"Seed complete: {s.created}. All seeded accounts use the password '{DEV_PASSWORD}'.", file=sys.stderr)


if __name__ == "__main__":
    main()
