"""Report-Phish workflow: learners submit, the analyzer triages, managers decide, feedback goes back in-app."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.ai import heuristics
from app.api.deps import DB, Learner, Manager, Paging, UserOnly, repo_for
from app.core.cache import cache
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.db.base import utcnow
from app.db.models import Campaign, ReportedEmail, SimulationEvent, Target, Template, User
from app.db.session import SessionLocal
from app.services.audit import audit_p
from app.services.notify import notify
from app.workers import webhooks

router = APIRouter(prefix="/reports", tags=["report-phish"])


class ReportIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    raw_text: str = Field(min_length=10, max_length=50_000)


def report_out(r: ReportedEmail, reporter: str | None = None) -> dict:
    return {"id": r.id, "subject": r.subject, "status": r.status, "heuristic_score": r.heuristic_score,
            "analysis": r.analysis, "feedback": r.feedback, "matched_campaign_id": r.matched_campaign_id,
            "reporter_user_id": r.reporter_user_id, "reporter": reporter, "created_at": r.created_at,
            "triaged_at": r.triaged_at, "raw_text": r.raw_text}


def triage_in_background(report_id: str) -> None:
    """Indicator Analyst (deterministic part) + match against this org's simulation templates."""
    db = SessionLocal()
    try:
        r = db.get(ReportedEmail, report_id)
        if not r:
            return
        result = heuristics.analyze(r.raw_text)
        r.heuristic_score, r.analysis = result["score"], result
        subj = r.subject.strip().lower().removeprefix("fw:").removeprefix("fwd:").strip()
        match = db.scalar(select(Campaign).join(Template, Template.id == Campaign.template_id).where(
            Campaign.org_id == r.org_id, Campaign.deleted_at.is_(None), func.lower(Template.subject) == subj))
        if match:
            r.matched_campaign_id = match.id
            r.analysis = {**result, "suggested_status": "confirmed_sim"}
            # count it as a 'reported' outcome for the simulation
            t = db.scalar(select(Target).where(Target.user_id == r.reporter_user_id))
            if t and not db.scalar(select(SimulationEvent.id).where(
                    SimulationEvent.campaign_id == match.id, SimulationEvent.target_id == t.id,
                    SimulationEvent.event_type == "reported")):
                db.add(SimulationEvent(org_id=r.org_id, campaign_id=match.id, target_id=t.id,
                                       department_id=t.department_id, event_type="reported",
                                       occurred_at=utcnow(), is_synthetic=False))
        db.commit()
        cache.invalidate_org(r.org_id)
    finally:
        db.close()


@router.post("", status_code=201, dependencies=[Depends(rate_limit("report", "rate_limit_report"))])
def submit_report(body: ReportIn, request: Request, principal: Learner, db: DB, background: BackgroundTasks,
                  _u: UserOnly):
    r = repo_for(principal, db).add(ReportedEmail, reporter_user_id=principal.id, subject=body.subject,
                                    raw_text=body.raw_text, status="new")
    audit_p(db, principal, request, "report.submitted", "reported_email", r.id)
    managers = db.scalars(select(User.id).where(User.org_id == principal.org_id, User.is_active.is_(True),
                                                User.role.in_(("manager", "org_admin")))).all()
    for mid in managers:
        notify(db, principal.org_id, mid, "report", "New phish report", body.subject[:120], "/reports/triage")
    notify(db, principal.org_id, principal.id, "report_feedback", "Report received",
           f"Thanks! '{body.subject[:80]}' is being checked. You'll be notified when a manager reviews it.",
           "/reports")
    ids = webhooks.enqueue(db, principal.org_id, "report.submitted", {"report_id": r.id, "subject": r.subject})
    db.commit()
    background.add_task(triage_in_background, r.id)
    if ids:
        background.add_task(webhooks.deliver, ids)
    return report_out(r)


@router.get("/mine")
def my_reports(principal: Learner, db: DB, p: Paging):
    repo = repo_for(principal, db)
    page = repo.paginate(repo.query(ReportedEmail).where(ReportedEmail.reporter_user_id == principal.id),
                         ReportedEmail, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         search=p.q, search_fields=("subject",), sortable=("created_at", "status"))
    page["items"] = [report_out(r) for r in page["items"]]
    return page


@router.get("")
def triage_queue(principal: Manager, db: DB, p: Paging,
                 status: Annotated[str | None, Query(pattern="^(new|triaged|confirmed_sim|benign)$")] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(ReportedEmail)
    if status:
        stmt = stmt.where(ReportedEmail.status == status)
    page = repo.paginate(stmt, ReportedEmail, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         search=p.q, search_fields=("subject",),
                         sortable=("created_at", "status", "heuristic_score"))
    names = dict(db.execute(select(User.id, User.full_name).where(
        User.id.in_([r.reporter_user_id for r in page["items"]]))).all())
    page["items"] = [report_out(r, names.get(r.reporter_user_id)) for r in page["items"]]
    return page


@router.get("/{report_id}")
def get_report(report_id: str, principal: Learner, db: DB):
    r = repo_for(principal, db).get(ReportedEmail, report_id)
    if principal.role == "learner" and r.reporter_user_id != principal.id:
        raise AppError("Report not found", code="not_found", status_code=404)
    return report_out(r)


class TriageIn(BaseModel):
    status: Literal["triaged", "confirmed_sim", "benign"]
    feedback: str = Field(default="", max_length=2000)


@router.post("/{report_id}/triage")
def triage(report_id: str, body: TriageIn, request: Request, principal: Manager, db: DB):
    r = repo_for(principal, db).get(ReportedEmail, report_id)
    old = r.status
    r.status, r.feedback, r.triaged_by, r.triaged_at = body.status, body.feedback or None, principal.id, utcnow()
    label = {"triaged": "is being reviewed", "confirmed_sim": "was a training simulation — well spotted!",
             "benign": "was reviewed and is safe"}[body.status]
    notify(db, principal.org_id, r.reporter_user_id, "report_feedback", f"Your report {label}",
           body.feedback or "Thanks for reporting.", "/reports")
    audit_p(db, principal, request, "report.triaged", "reported_email", r.id, **{"from": old, "to": body.status})
    db.commit()
    return report_out(r)
