"""Explainable risk scoring (0 = low risk, 100 = high risk).

score = 30 (baseline)
      + 50 * click_rate                (how often they clicked simulated lures)
      + 8 per click in the last 30 days (max 16)  (recency)
      - 25 * report_rate               (reporting is the behaviour we want)
      - 15 * training_completion       (completed / enrolled modules)
      + 5 per outstanding auto-enrolment (max 15)
clamped to [0, 100]. Each term is returned as a 'factor' so the UI can explain the number.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import Department, Enrollment, RiskScore, SimulationEvent, Target


def level(score: float) -> str:
    return "low" if score < 35 else "medium" if score < 60 else "high"


def score_from_stats(recipients: int, clicked: int, reported: int, recent_clicks: int,
                     enrolled: int, completed: int, outstanding_auto: int) -> tuple[float, list[dict[str, Any]]]:
    click_rate = clicked / recipients if recipients else 0.0
    report_rate = reported / recipients if recipients else 0.0
    completion = completed / enrolled if enrolled else 0.0
    factors = [
        {"key": "baseline", "label": "Baseline", "impact": 30.0, "detail": "Everyone starts at 30"},
        {"key": "click_rate", "label": "Simulated click rate", "impact": round(50 * click_rate, 1),
         "detail": f"{clicked} of {recipients} simulations clicked"},
        {"key": "recent_clicks", "label": "Recent clicks (30 days)", "impact": float(min(recent_clicks * 8, 16)),
         "detail": f"{recent_clicks} recent simulated clicks"},
        {"key": "report_rate", "label": "Reporting behaviour", "impact": round(-25 * report_rate, 1),
         "detail": f"{reported} of {recipients} simulations reported"},
        {"key": "training", "label": "Training completion", "impact": round(-15 * completion, 1),
         "detail": f"{completed} of {enrolled} modules completed"},
        {"key": "outstanding", "label": "Outstanding assigned training",
         "impact": float(min(outstanding_auto * 5, 15)), "detail": f"{outstanding_auto} auto-assigned not finished"},
    ]
    score = max(0.0, min(100.0, sum(f["impact"] for f in factors)))
    return round(score, 1), factors


def compute_target_scores(db: Session, org_id: str, as_of: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Compute scores for every target in the org using data up to `as_of` (default now)."""
    as_of = as_of or utcnow()
    since_recent = as_of - timedelta(days=30)
    targets = db.scalars(select(Target).where(Target.org_id == org_id, Target.deleted_at.is_(None))).all()
    stats: dict[str, dict[str, Any]] = {t.id: defaultdict(set) for t in targets}  # type: ignore[misc]
    events = db.execute(select(SimulationEvent.target_id, SimulationEvent.campaign_id, SimulationEvent.event_type,
                               SimulationEvent.occurred_at)
                        .where(SimulationEvent.org_id == org_id, SimulationEvent.occurred_at <= as_of,
                               SimulationEvent.deleted_at.is_(None))).all()
    for tid, cid, etype, at in events:
        if tid not in stats:
            continue
        stats[tid][etype].add(cid)
        if etype == "clicked_sim" and at >= since_recent:
            stats[tid]["recent"].add(cid)
    enrollments = db.execute(select(Enrollment.target_id, Enrollment.status, Enrollment.source, Enrollment.completed_at,
                                    Enrollment.created_at)
                             .where(Enrollment.org_id == org_id, Enrollment.deleted_at.is_(None))).all()
    enr: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for tid, status, source, done_at, created in enrollments:
        if created and created > as_of:
            continue
        enr[tid]["enrolled"] += 1
        if status == "completed" and (done_at is None or done_at <= as_of):
            enr[tid]["completed"] += 1
        elif source == "auto":
            enr[tid]["outstanding"] += 1
    out = {}
    for t in targets:
        s, e = stats[t.id], enr[t.id]
        score, factors = score_from_stats(len(s["delivered_preview"]), len(s["clicked_sim"]), len(s["reported"]),
                                          len(s["recent"]), e["enrolled"], e["completed"], e["outstanding"])
        out[t.id] = {"target_id": t.id, "name": t.full_name, "department_id": t.department_id,
                     "score": score, "level": level(score), "factors": factors}
    return out


def department_scores(db: Session, org_id: str, target_scores: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    names = dict(db.execute(select(Department.id, Department.name).where(Department.org_id == org_id,
                                                                         Department.deleted_at.is_(None))).all())
    groups: dict[str, list[float]] = defaultdict(list)
    for s in target_scores.values():
        groups[s["department_id"]].append(s["score"])
    rows = []
    for dept_id, scores in groups.items():
        avg = round(sum(scores) / len(scores), 1)
        rows.append({"department_id": dept_id, "department": names.get(dept_id, "?"), "score": avg,
                     "level": level(avg), "people": len(scores),
                     "high_risk_people": sum(1 for x in scores if x >= 60)})
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def snapshot(db: Session, org_id: str, as_of: datetime | None = None) -> int:
    """Persist a history row for every target and department. Returns rows written."""
    as_of = as_of or utcnow()
    targets = compute_target_scores(db, org_id, as_of)
    n = 0
    for t in targets.values():
        db.add(RiskScore(org_id=org_id, scope="target", subject_id=t["target_id"], score=t["score"],
                         factors=t["factors"], computed_at=as_of))
        n += 1
    for d in department_scores(db, org_id, targets):
        db.add(RiskScore(org_id=org_id, scope="department", subject_id=d["department_id"], score=d["score"],
                         factors=[], computed_at=as_of))
        n += 1
    db.flush()
    return n
