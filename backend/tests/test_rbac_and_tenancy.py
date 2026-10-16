"""RBAC matrix + tenant isolation (no cross-tenant leakage)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Campaign, Department, Organization, ReportedEmail, Target, Template
from tests.conftest import GLOBEX, login

# (method, path, minimum role) — status for roles below the minimum must be 403.
MATRIX = [
    ("GET", "/api/v1/campaigns", "manager"),
    ("GET", "/api/v1/templates", "manager"),
    ("GET", "/api/v1/analytics/overview", "manager"),
    ("GET", "/api/v1/risk/departments", "manager"),
    ("GET", "/api/v1/targets", "manager"),
    ("GET", "/api/v1/reports", "manager"),
    ("GET", "/api/v1/admin/users", "org_admin"),
    ("GET", "/api/v1/admin/audit", "org_admin"),
    ("GET", "/api/v1/admin/api-keys", "org_admin"),
    ("GET", "/api/v1/admin/webhooks", "org_admin"),
    ("GET", "/api/v1/training/modules", "learner"),
    ("GET", "/api/v1/inbox", "learner"),
    ("GET", "/api/v1/notifications", "learner"),
]
RANK = {"learner": 1, "manager": 2, "org_admin": 3, "super_admin": 4}
USERS = {"learner": "learner", "manager": "manager", "org_admin": "admin", "super_admin": "superadmin"}


@pytest.fixture(scope="module")
def sessions():
    return {role: login(f"{handle}@{GLOBEX}") for role, handle in USERS.items()}


@pytest.mark.parametrize("method,path,min_role", MATRIX)
@pytest.mark.parametrize("role", list(USERS))
def test_rbac_matrix(sessions, method, path, min_role, role):
    r = sessions[role].client.request(method, path)
    if RANK[role] >= RANK[min_role]:
        # inbox/training for staff without a learner profile may 404, but never 403
        assert r.status_code in (200, 404), (role, path, r.text)
    else:
        assert r.status_code == 403, (role, path, r.status_code)


def test_unauthenticated_is_401(anon):
    for _, path, _ in MATRIX:
        assert anon.get(path).status_code == 401


def _other_org_ids(db):
    initech = db.scalar(select(Organization).where(Organization.slug == "initech"))
    return {
        "campaign": db.scalar(select(Campaign.id).where(Campaign.org_id == initech.id)),
        "template": db.scalar(select(Template.id).where(Template.org_id == initech.id)),
        "target": db.scalar(select(Target.id).where(Target.org_id == initech.id)),
        "department": db.scalar(select(Department.id).where(Department.org_id == initech.id)),
        "report": db.scalar(select(ReportedEmail.id).where(ReportedEmail.org_id == initech.id)),
    }


def test_detail_endpoints_hide_other_tenants(admin, db):
    ids = _other_org_ids(db)
    for path in (f"/api/v1/campaigns/{ids['campaign']}", f"/api/v1/templates/{ids['template']}",
                 f"/api/v1/templates/{ids['template']}/preview", f"/api/v1/targets/{ids['target']}",
                 f"/api/v1/risk/targets/{ids['target']}", f"/api/v1/reports/{ids['report']}",
                 f"/api/v1/campaigns/{ids['campaign']}/events"):
        r = admin.get(path)
        assert r.status_code == 404, path  # same answer as "doesn't exist"


def test_mutations_cannot_touch_other_tenants(admin, db):
    ids = _other_org_ids(db)
    assert admin.patch(f"/api/v1/campaigns/{ids['campaign']}", json={"name": "hijack"}).status_code == 404
    assert admin.delete(f"/api/v1/templates/{ids['template']}").status_code == 404
    assert admin.post(f"/api/v1/reports/{ids['report']}/triage", json={"status": "benign"}).status_code == 404
    # Smuggling another org's department into a campaign is rejected.
    r = admin.post("/api/v1/campaigns", json={"name": "Cross tenant", "department_ids": [ids["department"]]})
    assert r.status_code == 404


def test_list_endpoints_only_return_own_tenant(admin, other_admin, db):
    globex = db.scalar(select(Organization).where(Organization.slug == "globex"))
    globex_campaigns = set(db.scalars(select(Campaign.id).where(Campaign.org_id == globex.id)).all())
    items = admin.get("/api/v1/campaigns?page_size=200").json()["items"]
    assert items and all(c["id"] in globex_campaigns for c in items)
    other = other_admin.get("/api/v1/campaigns?page_size=200").json()["items"]
    assert not {c["id"] for c in other} & globex_campaigns
    targets = admin.get("/api/v1/targets?page_size=200").json()["items"]
    assert all(t["email"].endswith(("example", "example.com")) for t in targets)


def test_analytics_are_tenant_scoped(admin, other_admin):
    a = admin.get("/api/v1/analytics/overview").json()["kpis"]["recipients"]
    b = other_admin.get("/api/v1/analytics/overview").json()["kpis"]["recipients"]
    assert a > 0 and b > 0 and a != b


def test_tenant_repo_requires_org():
    from app.db.repository import TenantRepo
    with pytest.raises(ValueError):
        TenantRepo(None, "")  # type: ignore[arg-type]
