from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password, password_policy_errors
from app.db.models import AuditLog, Organization, User
from app.main import app
from tests.conftest import GLOBEX, login


def _make_user(db, email: str, password: str = "Str0ng!Passw0rd", role: str = "learner") -> User:
    org = db.scalar(select(Organization).where(Organization.slug == "globex"))
    u = User(org_id=org.id, email=email, full_name="Test User", password_hash=hash_password(password), role=role)
    db.add(u)
    db.commit()
    return u


def test_login_sets_httponly_cookies_and_returns_csrf(anon):
    r = anon.post("/api/v1/auth/login", json={"email": f"admin@{GLOBEX}", "password": "PhishGuard!2026"})
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("pg_access="))
    assert "HttpOnly" in access and "SameSite=lax" in access
    csrf_cookie = next(c for c in cookies if c.startswith("pg_csrf="))
    assert "HttpOnly" not in csrf_cookie  # JS must read it for double-submit
    assert r.json()["csrf_token"] and r.json()["access_token"] is None


def test_bad_password_is_generic_401(anon):
    r = anon.post("/api/v1/auth/login", json={"email": f"admin@{GLOBEX}", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    r2 = anon.post("/api/v1/auth/login", json={"email": "nobody@globex.example.com", "password": "nope"})
    assert r2.json()["error"]["code"] == "invalid_credentials"  # no user enumeration


def test_lockout_after_repeated_failures(anon, db):
    _make_user(db, "lockme@globex.example.com")
    for _ in range(5):
        anon.post("/api/v1/auth/login", json={"email": "lockme@globex.example.com", "password": "wrong"})
    r = anon.post("/api/v1/auth/login", json={"email": "lockme@globex.example.com", "password": "Str0ng!Passw0rd"})
    assert r.status_code == 423
    assert r.json()["error"]["code"] == "account_locked"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.locked"))


def test_error_envelope_shape(anon):
    r = anon.get("/api/v1/campaigns")
    body = r.json()
    assert r.status_code == 401
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "details"}


def test_csrf_required_for_cookie_mutations(admin):
    r = admin.client.post("/api/v1/departments", json={"name": "No CSRF Dept"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = admin.post("/api/v1/departments", json={"name": "With CSRF Dept"})
    assert r.status_code == 201


def test_bearer_token_auth_needs_no_csrf(anon):
    r = anon.post("/api/v1/auth/login?include_token=true",
                  json={"email": f"manager@{GLOBEX}", "password": "PhishGuard!2026"})
    token = r.json()["access_token"]
    fresh = TestClient(app)
    r = fresh.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["role"] == "manager"


def test_refresh_rotation_and_reuse_detection(anon):
    r = anon.post("/api/v1/auth/login", json={"email": f"manager@{GLOBEX}", "password": "PhishGuard!2026"})
    old_refresh = r.cookies.get("pg_refresh") or anon.cookies.get("pg_refresh")
    assert old_refresh
    r2 = anon.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 200
    # Re-using the old (rotated) refresh token is treated as theft -> family revoked.
    r3 = anon.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r3.status_code == 401 and r3.json()["error"]["code"] == "refresh_reuse"
    new_refresh = r2.cookies.get("pg_refresh")
    r4 = anon.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r4.status_code == 401  # whole family is dead


def test_logout_revokes_access_token(anon):
    r = anon.post("/api/v1/auth/login?include_token=true",
                  json={"email": f"learner@{GLOBEX}", "password": "PhishGuard!2026"})
    token = r.json()["access_token"]
    assert anon.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    r = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_revoked"


def test_password_policy():
    assert password_policy_errors("short") != []
    assert password_policy_errors("alllowercaseletters1!") == ["an uppercase letter"]
    assert password_policy_errors("Str0ng!Passw0rd") == []


def test_totp_two_factor_flow(anon, db):
    _make_user(db, "totp@globex.example.com")
    s = login("totp@globex.example.com", "Str0ng!Passw0rd")
    secret = s.post("/api/v1/auth/2fa/setup").json()["secret"]
    assert s.post("/api/v1/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    r = anon.post("/api/v1/auth/login", json={"email": "totp@globex.example.com", "password": "Str0ng!Passw0rd"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "totp_required"
    r = anon.post("/api/v1/auth/login", json={"email": "totp@globex.example.com", "password": "Str0ng!Passw0rd",
                                              "totp_code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


def test_invite_flow_in_app_code(admin, anon):
    r = admin.post("/api/v1/admin/invites", json={"email": "newbie@globex.example.com", "role": "learner"})
    assert r.status_code == 201
    code = r.json()["code"]
    weak = anon.post("/api/v1/auth/invite/accept", json={"code": code, "full_name": "New Bie", "password": "weak"})
    assert weak.status_code == 422
    ok = anon.post("/api/v1/auth/invite/accept",
                   json={"code": code, "full_name": "New Bie", "password": "Str0ng!Passw0rd"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "learner"
    again = anon.post("/api/v1/auth/invite/accept",
                      json={"code": code, "full_name": "New Bie", "password": "Str0ng!Passw0rd"})
    assert again.status_code in (404, 409)


def test_admin_cannot_invite_super_admin(admin):
    r = admin.post("/api/v1/admin/invites", json={"email": "x@globex.example.com", "role": "super_admin"})
    assert r.status_code == 422  # not an allowed choice at all


def test_mock_oidc_login(anon):
    code = anon.post("/api/v1/auth/oidc/mock/authorize", json={"email": f"manager@{GLOBEX}"}).json()["code"]
    r = anon.post("/api/v1/auth/oidc/mock/callback", json={"code": code})
    assert r.status_code == 200 and r.json()["user"]["role"] == "manager"
    assert anon.post("/api/v1/auth/oidc/mock/callback", json={"code": code}).status_code == 401  # single use


def test_login_is_audited(db, anon):
    before = db.query(AuditLog).filter(AuditLog.action == "auth.login").count()
    anon.post("/api/v1/auth/login", json={"email": f"admin@{GLOBEX}", "password": "PhishGuard!2026"})
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "auth.login").count() == before + 1
