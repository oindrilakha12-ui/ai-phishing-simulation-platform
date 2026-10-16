from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from sqlalchemy import select

from app.db.models import Webhook, WebhookDelivery
from app.services.analytics import _kpis, _percentile
from app.services.exports import rows_to_csv
from app.services.risk import level, score_from_stats
from app.workers import webhooks

# ---------------------------------------------------------------- analytics math

def test_kpi_math():
    k = _kpis({"delivered_preview": 200, "clicked_sim": 30, "reported": 60, "previewed": 180})
    assert k["click_rate"] == 0.15 and k["report_rate"] == 0.3 and k["report_to_click_ratio"] == 2.0
    assert _kpis({})["click_rate"] == 0.0 and _kpis({})["report_to_click_ratio"] is None


def test_percentile():
    assert _percentile([1, 2, 3, 4], 0.5) == 2.5
    assert _percentile([10], 0.9) == 10
    assert _percentile([], 0.5) is None


def test_overview_shape_and_ranges(manager):
    data = manager.get("/api/v1/analytics/overview").json()
    k = data["kpis"]
    assert 0 <= k["click_rate"] <= 1 and 0 <= k["report_rate"] <= 1
    assert k["clicked"] <= k["recipients"]
    assert data["heatmap"] and data["trend"] and data["top_failed_flags"] and data["cohorts"]
    assert data["synthetic_data"] is True
    assert {c["cohort"] for c in data["cohorts"]} <= {"easy", "medium", "hard"}


def test_overview_filter_by_department(manager):
    dept = manager.get("/api/v1/departments?q=Finance").json()["items"][0]["id"]
    all_ = manager.get("/api/v1/analytics/overview").json()["kpis"]["recipients"]
    one = manager.get(f"/api/v1/analytics/overview?department_id={dept}").json()["kpis"]["recipients"]
    assert 0 < one < all_


def test_exports(manager):
    csv = manager.get("/api/v1/analytics/export.csv")
    assert csv.status_code == 200 and "click_rate" in csv.text and "SYNTHETIC" in csv.text
    pdf = manager.get("/api/v1/analytics/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_csv_formula_injection_neutralised():
    out = rows_to_csv([{"name": "=HYPERLINK(\"x\")"}], ["name"])
    assert "'=HYPERLINK" in out


def test_risk_score_is_explained_and_bounded():
    score, factors = score_from_stats(10, 10, 0, 3, 1, 0, 3)
    assert score == 100.0 or 0 <= score <= 100
    assert {f["key"] for f in factors} >= {"click_rate", "report_rate", "training"}
    good, _ = score_from_stats(10, 0, 10, 0, 3, 3, 0)
    assert good < 35 and level(good) == "low"


def test_risk_endpoints(manager):
    d = manager.get("/api/v1/risk/departments").json()
    assert d["current"] and d["history"]
    t = manager.get("/api/v1/risk/targets?page_size=5&sort=score&order=desc").json()
    assert t["items"][0]["score"] >= t["items"][-1]["score"]
    detail = manager.get(f"/api/v1/risk/targets/{t['items'][0]['target_id']}").json()
    assert detail["current"]["factors"] and len(detail["history"]) >= 1


# ---------------------------------------------------------------- training

def test_learner_completes_module_and_gets_certificate(learner, manager, admin):
    # A brand-new module so seed data can't have pre-completed it.
    module = admin.post("/api/v1/training/modules", json={
        "title": "Test Module", "category": "basics", "lessons": [
            {"title": "L1", "content_md": "Lesson one content"}, {"title": "L2", "content_md": "Lesson two content"}],
        "pass_mark": 100, "questions": [
            {"prompt": "Pick B please", "options": ["A", "B"], "correct_index": 1},
            {"prompt": "Pick B again", "options": ["A", "B", "C"], "correct_index": 1}]}).json()
    me_target = learner.get("/api/v1/auth/me/target").json()["target_id"]
    manager.post("/api/v1/training/enrollments", json={"module_id": module["id"], "target_ids": [me_target]})
    enr = next(e for e in learner.get("/api/v1/training/my").json() if e["module_id"] == module["id"])
    full = learner.get(f"/api/v1/training/modules/{module['id']}").json()
    assert "correct_index" not in json.dumps(full["quiz"])  # answers never sent before an attempt
    early = learner.post(f"/api/v1/training/enrollments/{enr['id']}/quiz", json={"answers": [0, 0]})
    assert early.status_code == 409
    for lesson in full["lessons"]:
        learner.post(f"/api/v1/training/enrollments/{enr['id']}/lessons/{lesson['id']}/complete")
    fail = learner.post(f"/api/v1/training/enrollments/{enr['id']}/quiz", json={"answers": [0, 0]}).json()
    assert fail["passed"] is False and fail["certificate_id"] is None
    ok = learner.post(f"/api/v1/training/enrollments/{enr['id']}/quiz", json={"answers": [1, 1]}).json()
    assert ok["passed"] is True and ok["score"] == 100 and ok["certificate_id"]
    pdf = learner.get(f"/api/v1/training/certificates/{ok['certificate_id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    badges = learner.get("/api/v1/training/badges/me").json()
    assert any(b["id"] == "perfect_quiz" and b["earned"] for b in badges["badges"])
    assert badges["streak_days"] >= 1


def test_leaderboard_is_privacy_aware(learner):
    lb = learner.get("/api/v1/training/leaderboard").json()
    assert lb["departments"]
    names = {i["name"] for i in lb["individuals"]}
    assert "Riley Learner" not in names  # did not opt in


# ---------------------------------------------------------------- admin: API keys, webhooks, audit

def test_api_key_scoped_read_only(admin, anon):
    r = admin.post("/api/v1/admin/api-keys", json={"name": "BI tool", "scopes": ["analytics:read"]})
    key = r.json()["key"]
    assert key.startswith("pg_")
    H = {"X-API-Key": key}
    assert anon.get("/api/v1/analytics/overview", headers=H).status_code == 200
    assert anon.get("/api/v1/campaigns", headers=H).status_code == 403
    assert anon.post("/api/v1/risk/recompute", headers=H).status_code == 403
    admin.delete(f"/api/v1/admin/api-keys/{r.json()['id']}")
    assert anon.get("/api/v1/analytics/overview", headers=H).status_code == 401


def test_webhook_hmac_signature_and_retry(admin, db):
    hook = admin.post("/api/v1/admin/webhooks", json={"url": "https://hooks.example/receiver",
                                                      "events": ["webhook.test"]}).json()
    secret = hook["secret"]
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(500 if len(seen) == 1 else 200)

    d = WebhookDelivery(org_id=db.scalar(select(Webhook.org_id).where(Webhook.id == hook["id"])),
                        webhook_id=hook["id"], event="webhook.test", payload={"x": 1})
    db.add(d)
    db.commit()
    webhooks.deliver([d.id], sleep=lambda s: None, client=httpx.Client(transport=httpx.MockTransport(handler)))
    db.expire_all()
    d = db.get(WebhookDelivery, d.id)
    assert d.status == "success" and d.attempts == 2
    sig = seen[-1].headers[webhooks.SIGNATURE_HEADER]
    ts, mac = sig.split(",")[0][2:], sig.split("v1=")[1]
    expected = hmac.new(secret.encode(), ts.encode() + b"." + seen[-1].content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(mac, expected)
    assert json.loads(seen[-1].content)["event"] == "webhook.test"
    log = admin.get(f"/api/v1/admin/webhooks/{hook['id']}/deliveries").json()["items"]
    assert log and log[0]["status"] in ("success", "failed", "pending")


def test_webhook_rejects_non_http_urls(admin):
    assert admin.post("/api/v1/admin/webhooks", json={"url": "ftp://x.example/a"}).status_code == 422


def test_audit_log_filters_and_export(admin):
    admin.post("/api/v1/departments", json={"name": "Audit Dept"})
    items = admin.get("/api/v1/admin/audit?action=department.").json()["items"]
    assert items and all(i["action"].startswith("department.") for i in items)
    assert items[0]["ip"] and items[0]["request_id"] and items[0]["actor_email"]
    csv = admin.get("/api/v1/admin/audit/export.csv")
    assert csv.status_code == 200 and "action" in csv.text.splitlines()[0]


def test_admin_user_management_guards(admin, super_admin):
    users = admin.get("/api/v1/admin/users?q=superadmin").json()["items"]
    assert admin.patch(f"/api/v1/admin/users/{users[0]['id']}", json={"is_active": False}).status_code == 403
    me = admin.user["id"]
    assert admin.patch(f"/api/v1/admin/users/{me}", json={"role": "learner"}).status_code == 400
    orgs = super_admin.get("/api/v1/admin/organizations").json()
    assert len(orgs) == 2
    assert len(admin.get("/api/v1/admin/organizations").json()) == 1


def test_health_and_metrics(anon):
    r = anon.get("/health/ready").json()
    assert r["database"] == "sqlite" and r["demo_mode"] is True
    m = anon.get("/metrics")
    assert "phishguard_http_requests_total" in m.text
    assert anon.get("/health/live").headers["X-Content-Type-Options"] == "nosniff"


def test_migrations_match_models(tmp_path):
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from alembic import command
    from app.db.base import Base

    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
