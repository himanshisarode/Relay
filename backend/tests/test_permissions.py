"""Table-driven permission matrix (spec 16): role x policy x grant state x resource status."""

import pytest

from app.services.permissions import ResourceFacts, UserFacts, can_decide, can_manage, decide

LAB, OTHER_LAB_SAME_DEPT, LAB_OTHER_DEPT = 1, 2, 3
DEPT, OTHER_DEPT = 10, 20
RES = 100

ROLES: dict[str, UserFacts] = {
    "superadmin": UserFacts(1, is_superadmin=True),
    "dept_admin": UserFacts(2, admin_department_ids=frozenset({DEPT}), verified_department_ids=frozenset({DEPT})),
    "other_dept_admin": UserFacts(3, admin_department_ids=frozenset({OTHER_DEPT}),
                                  verified_department_ids=frozenset({OTHER_DEPT})),
    "professor": UserFacts(4, professor_lab_ids=frozenset({LAB}), lab_ids=frozenset({LAB}),
                           lab_department_ids=frozenset({DEPT}), verified_department_ids=frozenset({DEPT})),
    "professor_sibling_lab": UserFacts(5, professor_lab_ids=frozenset({OTHER_LAB_SAME_DEPT}),
                                       lab_ids=frozenset({OTHER_LAB_SAME_DEPT}), lab_department_ids=frozenset({DEPT}),
                                       verified_department_ids=frozenset({DEPT})),
    "lab_member": UserFacts(6, lab_ids=frozenset({LAB}), lab_department_ids=frozenset({DEPT}),
                            verified_department_ids=frozenset({DEPT})),
    "sibling_lab_member": UserFacts(7, lab_ids=frozenset({OTHER_LAB_SAME_DEPT}), lab_department_ids=frozenset({DEPT})),
    "dept_member_verified": UserFacts(8, verified_department_ids=frozenset({DEPT})),
    "dept_member_unverified": UserFacts(9),  # claimed the department at signup, not yet confirmed
    "other_dept_member": UserFacts(10, lab_ids=frozenset({LAB_OTHER_DEPT}), lab_department_ids=frozenset({OTHER_DEPT}),
                                   verified_department_ids=frozenset({OTHER_DEPT})),
    "outsider": UserFacts(11),
}

Y, N = True, False
# Expected result with an active resource and no grant.     lab_only  department  inst_approval  inst_open
EXPECTED = {
    "superadmin":             (Y, Y, Y, Y),
    "dept_admin":             (Y, Y, Y, Y),
    "other_dept_admin":       (N, N, N, Y),
    "professor":              (Y, Y, Y, Y),
    "professor_sibling_lab":  (N, Y, N, Y),
    "lab_member":             (Y, Y, N, Y),
    "sibling_lab_member":     (N, Y, N, Y),
    "dept_member_verified":   (N, Y, N, Y),
    "dept_member_unverified": (N, N, N, Y),
    "other_dept_member":      (N, N, N, Y),
    "outsider":               (N, N, N, Y),
}
POLICIES = ("lab_only", "department", "institute_approval", "institute_open")


def resource(policy: str, status: str = "active", accepts: bool = True) -> ResourceFacts:
    return ResourceFacts(RES, LAB, DEPT, policy, accepts, status)


def with_grant(u: UserFacts) -> UserFacts:
    return UserFacts(**{**u.__dict__, "grants": {RES: 999}})


def unverified(u: UserFacts) -> UserFacts:
    return UserFacts(**{**u.__dict__, "email_verified": False})


CASES = [(role, policy, EXPECTED[role][i]) for role in ROLES for i, policy in enumerate(POLICIES)]


@pytest.mark.parametrize("role,policy,expected", CASES)
def test_matrix_no_grant(role, policy, expected):
    d = decide(ROLES[role], resource(policy))
    assert d.allowed is expected
    if not expected:
        assert d.can_request_access is True  # accepts_requests defaults to true


@pytest.mark.parametrize("role,policy,_", CASES)
def test_matrix_with_active_grant_always_allows(role, policy, _):
    d = decide(with_grant(ROLES[role]), resource(policy))
    assert d.allowed
    # Privileged users stay privileged (exempt from quota) even if they also hold a grant.
    assert d.via in ("privileged", "grant", "policy")


@pytest.mark.parametrize("role,policy,_", CASES)
@pytest.mark.parametrize("status", ["maintenance", "retired"])
def test_inactive_resource_denies_everyone(role, policy, _, status):
    d = decide(with_grant(ROLES[role]), resource(policy, status))
    assert not d.allowed and d.reason == "resource_unavailable" and not d.can_request_access


@pytest.mark.parametrize("role,policy,_", CASES)
def test_unverified_email_denies_everyone(role, policy, _):
    d = decide(with_grant(unverified(ROLES[role])), resource(policy))
    assert not d.allowed and d.reason == "email_not_verified"


def test_inactive_account_denied():
    d = decide(UserFacts(1, is_active=False, is_superadmin=True), resource("institute_open"))
    assert not d.allowed and d.reason == "account_inactive"


def test_grant_is_what_allows_institute_approval():
    d = decide(with_grant(ROLES["outsider"]), resource("institute_approval"))
    assert d.allowed and d.via == "grant" and d.grant_id == 999 and not d.privileged


def test_can_request_access_false_when_resource_closed_to_requests():
    d = decide(ROLES["outsider"], resource("department", accepts=False))
    assert not d.allowed and d.can_request_access is False


@pytest.mark.parametrize("role,expected", [
    ("superadmin", True), ("dept_admin", True), ("professor", True), ("other_dept_admin", False),
    ("professor_sibling_lab", False), ("lab_member", False), ("outsider", False),
])
def test_can_manage(role, expected):
    assert can_manage(ROLES[role], resource("lab_only")) is expected
    assert decide(ROLES[role], resource("lab_only")).privileged is expected


def test_professor_cannot_decide_own_request():
    prof = ROLES["professor"]
    assert can_decide(prof, resource("lab_only"), requester_id=6)
    assert not can_decide(prof, resource("lab_only"), requester_id=prof.user_id)  # AC-R3


def test_manager_elsewhere_cannot_decide_own_request_here():
    """AC-R3: being the professor of some other lab gives no power over your own request."""
    sib = ROLES["professor_sibling_lab"]
    assert not can_decide(sib, resource("institute_approval"), requester_id=sib.user_id)
