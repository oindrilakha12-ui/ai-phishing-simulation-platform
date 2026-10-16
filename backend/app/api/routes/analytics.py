"""Analytics dashboard data, risk scores and CSV/PDF exports."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import DB, Manager, Paging, Principal, repo_for, require_role
from app.core.cache import cache
from app.db.models import Organization, RiskScore, Target
from app.services.analytics import Filters, live_activity, overview
from app.services.audit import audit_p
from app.services.exports import analytics_csv, analytics_pdf, rows_to_csv
from app.services.risk import compute_target_scores, department_scores, snapshot

router = APIRouter(tags=["analytics"])
AnalyticsReader = Annotated[Principal, Depends(require_role("manager", api_scope="analytics:read"))]


def _filters(campaign_id: Annotated[str | None, Query(max_length=32)] = None,
             department_id: Annotated[str | None, Query(max_length=32)] = None,
             date_from: datetime | None = None, date_to: datetime | None = None,
             real_only: bool = False) -> Filters:
    return Filters(campaign_id, department_id, date_from, date_to, real_only)


F = Annotated[Filters, Depends(_filters)]


@router.get("/analytics/overview")
def analytics_overview(principal: AnalyticsReader, db: DB, f: F):
    return overview(db, principal.org_id, f)


@router.get("/analytics/live-activity")
def analytics_live_activity(principal: AnalyticsReader, db: DB,
                            limit: Annotated[int, Query(ge=1, le=50)] = 20):
    """Latest actions by real logged-in users (inbox clicks/reports, report submissions)."""
    return {"items": live_activity(db, principal.org_id, limit)}


@router.get("/analytics/export.csv")
def export_csv(request: Request, principal: Manager, db: DB, f: F):
    org = db.get(Organization, principal.org_id)
    body = analytics_csv(overview(db, principal.org_id, f), org.name)
    audit_p(db, principal, request, "analytics.exported", "analytics", None, format="csv")
    db.commit()
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="phishguard-analytics.csv"'})


@router.get("/analytics/export.pdf")
def export_pdf(request: Request, principal: Manager, db: DB, f: F):
    org = db.get(Organization, principal.org_id)
    risk = department_scores(db, principal.org_id, _cached_scores(db, principal.org_id))
    pdf = analytics_pdf(overview(db, principal.org_id, f), org.name, risk)
    audit_p(db, principal, request, "analytics.exported", "analytics", None, format="pdf")
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="phishguard-compliance-report.pdf"'})


# ---------------------------------------------------------------- risk

def _cached_scores(db, org_id: str) -> dict:
    return cache.get_or_set(f"org:{org_id}:risk", lambda: compute_target_scores(db, org_id))


@router.get("/risk/targets")
def risk_targets(principal: AnalyticsReader, db: DB, p: Paging,
                 department_id: Annotated[str | None, Query(max_length=32)] = None,
                 level: Annotated[str | None, Query(pattern="^(low|medium|high)$")] = None):
    rows = list(_cached_scores(db, principal.org_id).values())
    if department_id:
        rows = [r for r in rows if r["department_id"] == department_id]
    if level:
        rows = [r for r in rows if r["level"] == level]
    if p.q:
        rows = [r for r in rows if p.q.lower() in r["name"].lower()]
    key = p.sort if p.sort in ("score", "name") else "score"
    rows.sort(key=lambda r: r[key], reverse=p.order == "desc")
    start = (p.page - 1) * p.page_size
    return {"items": rows[start:start + p.page_size], "total": len(rows), "page": p.page, "page_size": p.page_size}


@router.get("/risk/targets/{target_id}")
def risk_target(target_id: str, principal: AnalyticsReader, db: DB):
    repo = repo_for(principal, db)
    t = repo.get(Target, target_id)
    history = db.scalars(repo.query(RiskScore).where(RiskScore.scope == "target", RiskScore.subject_id == t.id)
                         .order_by(RiskScore.computed_at)).all()
    return {"current": _cached_scores(db, principal.org_id).get(t.id),
            "history": [{"at": h.computed_at, "score": h.score} for h in history]}


@router.get("/risk/departments")
def risk_departments(principal: AnalyticsReader, db: DB):
    repo = repo_for(principal, db)
    current = department_scores(db, principal.org_id, _cached_scores(db, principal.org_id))
    history = db.execute(select(RiskScore.subject_id, RiskScore.computed_at, RiskScore.score)
                         .where(RiskScore.org_id == repo.org_id, RiskScore.scope == "department",
                                RiskScore.deleted_at.is_(None))
                         .order_by(RiskScore.computed_at)).all()
    hist: dict[str, list] = {}
    for sid, at, score in history:
        hist.setdefault(sid, []).append({"at": at, "score": score})
    return {"current": current, "history": hist}


@router.post("/risk/recompute")
def risk_recompute(request: Request, principal: Manager, db: DB):
    n = snapshot(db, principal.org_id)
    audit_p(db, principal, request, "risk.recomputed", "risk", None, rows=n)
    db.commit()
    cache.invalidate_org(principal.org_id)
    return {"message": f"Recorded {n} risk scores"}


@router.get("/risk/export.csv")
def risk_export(request: Request, principal: Manager, db: DB):
    rows = sorted(_cached_scores(db, principal.org_id).values(), key=lambda r: -r["score"])
    audit_p(db, principal, request, "risk.exported", "risk", None)
    db.commit()
    return Response(rows_to_csv(rows, ["name", "department_id", "score", "level"]), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="phishguard-risk.csv"'})
