from pathlib import Path

import yaml
from sqlalchemy import func, select

from app.models import Booking, Department, Lab, LabMember, Resource
from scripts.seed import SEED_FILE, Seeder


def test_seed_runs_twice_and_matches_yaml(db):
    data = yaml.safe_load(Path(SEED_FILE).read_text(encoding="utf-8"))
    for _ in range(2):
        s = Seeder(db)
        s.run(data)
        s.demo()
        db.commit()
    n_res = sum(len(lab["resources"]) for d in data["departments"] for lab in d["labs"])
    assert db.scalar(select(func.count()).select_from(Department)) == len(data["departments"])
    assert db.scalar(select(func.count()).select_from(Resource)) == n_res
    # Every lab has exactly one professor.
    profs = db.execute(select(Lab.id, func.count(LabMember.user_id)).outerjoin(
        LabMember, (LabMember.lab_id == Lab.id) & (LabMember.role == "professor")).group_by(Lab.id)).all()
    assert all(n == 1 for _, n in profs)
    assert db.scalar(select(func.count()).select_from(Booking)) > 50
