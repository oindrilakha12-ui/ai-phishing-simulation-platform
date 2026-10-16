from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import AuditLog, SimulationEvent


def _template_and_dept(s):
    t = s.get("/api/v1/templates?difficulty=easy").json()["items"][0]
    d = s.get("/api/v1/departments?q=Finance").json()["items"][0]  # seeded dept with people
    return t["id"], d["id"]


def test_campaign_crud_and_lifecycle(manager, db):
    tid, did = _template_and_dept(manager)
    r = manager.post("/api/v1/campaigns", json={"name": "Lifecycle test", "template_id": tid,
                                                "department_ids": [did, did]})
    assert r.status_code == 201
    c = r.json()
    assert c["status"] == "draft" and c["department_ids"] == [did]  # de-duplicated

    # draft -> scheduled requires scheduled_at
    r = manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "scheduled"})
    assert r.status_code == 422 and "scheduled_at" in r.json()["error"]["details"]["missing"]
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert manager.patch(f"/api/v1/campaigns/{c['id']}", json={"scheduled_at": when}).status_code == 200
    assert manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "scheduled"}).json()["status"] == \
        "scheduled"

    # invalid jump
    r = manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"

    # activate -> synthetic events generated in background (TestClient runs it before returning)
    assert manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "active"}).status_code == 200
    n = db.scalar(select(func.count()).select_from(SimulationEvent).where(SimulationEvent.campaign_id == c["id"]))
    assert n > 0
    assert db.scalar(select(func.count()).select_from(SimulationEvent).where(
        SimulationEvent.campaign_id == c["id"], SimulationEvent.is_synthetic.is_(False))) == 0

    # active campaigns are locked for edit and delete
    assert manager.patch(f"/api/v1/campaigns/{c['id']}", json={"name": "x" * 5}).status_code == 409
    assert manager.delete(f"/api/v1/campaigns/{c['id']}").status_code == 409

    detail = manager.get(f"/api/v1/campaigns/{c['id']}").json()
    assert detail["stats"]["recipients"] > 0

    assert manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "completed"}).status_code == 200
    assert manager.delete(f"/api/v1/campaigns/{c['id']}").status_code == 200
    assert manager.get(f"/api/v1/campaigns/{c['id']}").status_code == 404  # soft-deleted
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == c["id"])).all())
    assert {"campaign.created", "campaign.updated", "campaign.transition", "campaign.deleted"} <= actions


def test_list_pagination_filter_sort_search(manager):
    r = manager.get("/api/v1/campaigns?page=1&page_size=3&sort=name&order=asc")
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) == 3 and body["total"] >= 3
    names = [c["name"] for c in body["items"]]
    assert names == sorted(names)
    assert all(c["status"] == "completed" for c in manager.get("/api/v1/campaigns?status=completed").json()["items"])
    assert manager.get("/api/v1/campaigns?q=payroll").json()["total"] >= 1
    bad = manager.get("/api/v1/campaigns?sort=password_hash")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_sort"
    assert manager.get("/api/v1/campaigns?page_size=1000").status_code == 422


def test_validation_and_size_limits(manager):
    assert manager.post("/api/v1/campaigns", json={"name": "x"}).status_code == 422
    huge = manager.post("/api/v1/campaigns", content=b"{" + b" " * 300_000 + b"}",
                        headers={"Content-Type": "application/json"})
    assert huge.status_code == 413


def test_scheduler_activates_due_campaigns(manager, db):
    tid, did = _template_and_dept(manager)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    c = manager.post("/api/v1/campaigns", json={"name": "Due now", "template_id": tid, "department_ids": [did],
                                                "scheduled_at": past}).json()
    manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "scheduled"})
    assert "Activated" in manager.post("/api/v1/campaigns/run-scheduler").json()["message"]
    assert manager.get(f"/api/v1/campaigns/{c['id']}").json()["status"] == "active"


def test_learner_inbox_click_auto_enrolls_and_shows_landing(learner, manager):
    tid, _ = _template_and_dept(manager)
    me_dept = learner.user["department_id"]
    c = manager.post("/api/v1/campaigns", json={"name": "Inbox test", "template_id": tid,
                                                "department_ids": [me_dept]}).json()
    manager.post(f"/api/v1/campaigns/{c['id']}/transition", json={"to": "active"})
    inbox = learner.get("/api/v1/inbox").json()
    assert any(i["campaign_id"] == c["id"] for i in inbox)
    preview = learner.get(f"/api/v1/inbox/{c['id']}/preview").json()
    assert preview["red_flags"] == [] and "SIMULATION" in preview["document"]
    r = learner.post(f"/api/v1/inbox/{c['id']}/action", json={"action": "clicked_sim"}).json()
    assert "<input" not in r["landing_page"].lower() and "<form" not in r["landing_page"].lower()
    assert r["red_flags"] and r["enrolled_module"]
    assert any(e["source"] == "auto" for e in learner.get("/api/v1/training/my").json())
