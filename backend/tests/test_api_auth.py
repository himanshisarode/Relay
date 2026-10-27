import re

import pytest

from tests.conftest import login

PUBLIC = {
    ("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/verify-email"), ("POST", "/api/v1/auth/verify-email/resend"),
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/confirm"), ("GET", "/api/v1/departments"),
    ("GET", "/api/v1/departments/{department_id}/labs"),
}


def _routes():
    # The OpenAPI schema lists every mounted route with its full path, however routers are nested.
    from app.main import app

    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/v1"):
            for m in ops:
                if (m.upper(), path) not in PUBLIC:
                    yield m.upper(), path


ROUTES = sorted(set(_routes()))


def test_route_table_is_populated():
    """Guard: if route discovery breaks, the auth test below must not silently check nothing."""
    assert len(ROUTES) >= 40, ROUTES


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_protected_route_requires_auth(client, method, path):
    url = re.sub(r"\{[^}]+\}", "1", path)
    if "availability" in url:
        url += "?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z"
    r = client.request(method, url, json={})
    assert r.status_code == 401, (method, path, r.text)
    assert r.json()["error"]["code"] == "unauthenticated"


def test_register_verify_login_flow(client, world):
    r = client.post("/api/v1/auth/register", json={"name": "Asha Rao", "email": "asha@test.local",
                                                   "password": "long-enough-pw", "department_id": world.phy.id})
    assert r.status_code == 201
    token = r.json()["dev_token"]
    me = login(client, "asha@test.local", "long-enough-pw").get("/api/v1/auth/me").json()
    assert me["email_verified"] is False
    assert me["departments"] == [{"id": world.phy.id, "code": "PHY", "name": "Physics", "role": "member", "verified": False}]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["email_verified"] is True
    # Tokens are single use.
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).json()["error"]["code"] == "invalid_token"


def test_duplicate_email_case_insensitive(client, world):
    r = client.post("/api/v1/auth/register", json={"name": "X Y", "email": "ADMIN@test.local", "password": "long-enough-pw"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_bad_password(client, world):
    r = client.post("/api/v1/auth/login", json={"email": world.admin.email, "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"


def test_csrf_required_on_writes(client, world):
    login(client, world.student_qm)
    del client.headers["X-CSRF-Token"]
    r = client.post("/api/v1/notifications/read-all")
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_logout_revokes_session(client, world):
    login(client, world.student_qm)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_revokes_sessions(client, world):
    login(client, world.student_qm)
    token = client.post("/api/v1/auth/password-reset/request", json={"email": world.student_qm.email}).json()["dev_token"]
    assert client.post("/api/v1/auth/password-reset/confirm",
                       json={"token": token, "password": "a-brand-new-password"}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, world.student_qm.email, "a-brand-new-password")


def test_reset_request_does_not_reveal_accounts(client, world):
    r = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@test.local"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_rate_limit(client, world, monkeypatch):
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    codes = [client.post("/api/v1/auth/login", json={"email": "x@test.local", "password": "nope"}).status_code
             for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[-1] == 429


def test_error_shape_for_validation(client, world):
    r = client.post("/api/v1/auth/register", json={"email": "not-an-email"})
    body = r.json()
    assert r.status_code == 422 and set(body["error"]) == {"code", "message", "details"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
