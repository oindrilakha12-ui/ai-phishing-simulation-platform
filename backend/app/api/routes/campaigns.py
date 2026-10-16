"""Campaign CRUD + lifecycle (draft -> scheduled -> active -> completed) and the learner inbox."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, Learner, Manager, Paging, UserOnly, repo_for
from app.api.routes.templates import render_preview
from app.core.cache import cache
from app.core.errors import AppError, NotFound
from app.db.base import utcnow
from app.db.models import Campaign, Department, SimulationEvent, Target, Template, User
from app.db.session import SessionLocal
from app.schemas.common import Message, Page
from app.schemas.domain import CampaignIn, CampaignOut, CampaignTransition, CampaignUpdate
from app.services.analytics import campaign_stats
from app.services.audit import audit_p
from app.services.notify import notify
from app.services.safety import build_landing_page
from app.services.simulation import simulate_campaign
from app.services.training import auto_enroll_for_failure
from app.workers import webhooks

router = APIRouter(tags=["campaigns"])

# Allowed lifecycle transitions. Anything else is rejected with 409.
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"scheduled", "active"},
    "scheduled": {"draft", "active"},
    "active": {"completed"},
    "completed": set(),
}


def campaign_out(c: Campaign, stats: dict | None = None) -> dict:
    data = CampaignOut.model_validate(c).model_dump()
    data["template_name"] = c.template.name if c.template else None
    data["template_difficulty"] = c.template.difficulty if c.template else None
    data["department_ids"] = [d.id for d in c.departments]
    data["department_names"] = [d.name for d in c.departments]
    data["stats"] = stats
    return data


def _resolve_departments(repo, ids: list[str]) -> list[Department]:
    depts = []
    for did in dict.fromkeys(ids):  # de-duplicate, keep order
        depts.append(repo.get(Department, did))  # 404 if another org's id is supplied
    return depts


@router.get("/campaigns", response_model=Page[CampaignOut])
def list_campaigns(principal: Manager, db: DB, p: Paging,
                   status: Annotated[str | None, Query(pattern="^(draft|scheduled|active|completed)$")] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(Campaign)
    if status:
        stmt = stmt.where(Campaign.status == status)
    page = repo.paginate(stmt, Campaign, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         search=p.q, search_fields=("name", "description"),
                         sortable=("created_at", "name", "status", "started_at", "scheduled_at"))
    stats = campaign_stats(db, principal.org_id, [c.id for c in page["items"]])
    page["items"] = [campaign_out(c, stats.get(c.id)) for c in page["items"]]
    return page


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(body: CampaignIn, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    if body.template_id:
        repo.get(Template, body.template_id)
    depts = _resolve_departments(repo, body.department_ids)
    c = repo.add(Campaign, name=body.name, description=body.description, template_id=body.template_id,
                 scheduled_at=body.scheduled_at, status="draft", created_by=principal.id)
    c.departments = depts
    audit_p(db, principal, request, "campaign.created", "campaign", c.id, name=c.name)
    db.commit()
    db.refresh(c)
    return campaign_out(c)


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str, principal: Manager, db: DB):
    c = repo_for(principal, db).get(Campaign, campaign_id)
    return campaign_out(c, campaign_stats(db, principal.org_id, [c.id]).get(c.id))


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: str, body: CampaignUpdate, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    c = repo.get(Campaign, campaign_id)
    if c.status not in ("draft", "scheduled"):
        raise AppError("Only draft or scheduled campaigns can be edited", code="campaign_locked", status_code=409)
    changes = body.model_dump(exclude_unset=True)
    if "template_id" in changes and changes["template_id"]:
        repo.get(Template, changes["template_id"])
    if "department_ids" in changes:
        c.departments = _resolve_departments(repo, changes.pop("department_ids") or [])
    for k, v in changes.items():
        setattr(c, k, v)
    audit_p(db, principal, request, "campaign.updated", "campaign", c.id, fields=sorted(body.model_dump(exclude_unset=True)))
    db.commit()
    db.refresh(c)
    return campaign_out(c)


@router.delete("/campaigns/{campaign_id}", response_model=Message)
def delete_campaign(campaign_id: str, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    c = repo.get(Campaign, campaign_id)
    if c.status == "active":
        raise AppError("Complete the campaign before deleting it", code="campaign_active", status_code=409)
    repo.soft_delete(c)
    audit_p(db, principal, request, "campaign.deleted", "campaign", c.id)
    cache.invalidate_org(principal.org_id)
    db.commit()
    return {"message": "Campaign deleted"}


def _launch_in_background(campaign_id: str, org_id: str) -> None:
    """Generate synthetic outcomes in a fresh session (runs after the response is sent)."""
    db = SessionLocal()
    try:
        c = db.get(Campaign, campaign_id)
        if c is None or c.org_id != org_id:
            return
        n = simulate_campaign(db, c, start=c.started_at or utcnow())
        ids = webhooks.enqueue(db, org_id, "campaign.activated", {"campaign_id": c.id, "name": c.name,
                                                                  "synthetic_events": n})
        # Tell learners (only those with accounts) that a training simulation is in their inbox.
        user_ids = db.scalars(select(Target.user_id).where(
            Target.org_id == org_id, Target.user_id.is_not(None),
            Target.department_id.in_([d.id for d in c.departments]))).all()
        for uid in user_ids:
            notify(db, org_id, uid, "simulation", "New training simulation in your inbox",
                   f"Can you spot the red flags in '{c.name}'?", "/inbox")
        db.commit()
        cache.invalidate_org(org_id)
        if ids:
            webhooks.deliver(ids)
    finally:
        db.close()


def check_transition(current: str, target: str, c: Campaign) -> None:
    if target not in TRANSITIONS[current]:
        raise AppError(f"Cannot move a campaign from {current} to {target}", code="invalid_transition",
                       status_code=409, details={"allowed": sorted(TRANSITIONS[current])})
    if target in ("scheduled", "active"):
        missing = [n for n, ok in (("template", c.template_id), ("departments", c.departments)) if not ok]
        if target == "scheduled" and not c.scheduled_at:
            missing.append("scheduled_at")
        if missing:
            raise AppError("Campaign is incomplete", code="campaign_incomplete", status_code=422,
                           details={"missing": missing})


@router.post("/campaigns/{campaign_id}/transition", response_model=CampaignOut)
def transition_campaign(campaign_id: str, body: CampaignTransition, request: Request, principal: Manager,
                        db: DB, background: BackgroundTasks):
    c = repo_for(principal, db).get(Campaign, campaign_id)
    check_transition(c.status, body.to, c)
    old = c.status
    c.status = body.to
    if body.to == "active":
        c.started_at = utcnow()
        background.add_task(_launch_in_background, c.id, principal.org_id)
    elif body.to == "completed":
        c.completed_at = utcnow()
        ids = webhooks.enqueue(db, principal.org_id, "campaign.completed", {"campaign_id": c.id, "name": c.name})
        if ids:
            background.add_task(webhooks.deliver, ids)
    audit_p(db, principal, request, "campaign.transition", "campaign", c.id, **{"from": old, "to": body.to})
    db.commit()
    cache.invalidate_org(principal.org_id)
    return campaign_out(c)


@router.post("/campaigns/run-scheduler", response_model=Message)
def run_scheduler(request: Request, principal: Manager, db: DB, background: BackgroundTasks):
    """Activate scheduled campaigns whose time has come (also runs periodically in-process)."""
    n = activate_due_campaigns(db, principal.org_id, background)
    audit_p(db, principal, request, "campaign.scheduler_run", "campaign", None, activated=n)
    db.commit()
    return {"message": f"Activated {n} campaign(s)"}


def activate_due_campaigns(db, org_id: str | None, background: BackgroundTasks | None = None) -> int:
    stmt = select(Campaign).where(Campaign.status == "scheduled", Campaign.scheduled_at <= utcnow(),
                                  Campaign.deleted_at.is_(None))
    if org_id:
        stmt = stmt.where(Campaign.org_id == org_id)
    due = db.scalars(stmt).all()
    for c in due:
        c.status, c.started_at = "active", utcnow()
        db.commit()
        if background is not None:
            background.add_task(_launch_in_background, c.id, c.org_id)
        else:
            _launch_in_background(c.id, c.org_id)
    return len(due)


@router.get("/campaigns/{campaign_id}/events")
def campaign_events(campaign_id: str, principal: Manager, db: DB, p: Paging,
                    event_type: Annotated[str | None, Query(max_length=24)] = None):
    repo = repo_for(principal, db)
    repo.get(Campaign, campaign_id)
    stmt = repo.query(SimulationEvent).where(SimulationEvent.campaign_id == campaign_id)
    if event_type:
        stmt = stmt.where(SimulationEvent.event_type == event_type)
    page = repo.paginate(stmt, SimulationEvent, page=p.page, page_size=p.page_size, sort=p.sort or "occurred_at",
                         order=p.order, sortable=("occurred_at", "event_type"))
    names = dict(db.execute(select(Target.id, Target.full_name).where(
        Target.id.in_([e.target_id for e in page["items"]]))).all())
    page["items"] = [{"id": e.id, "target_id": e.target_id, "target_name": names.get(e.target_id),
                      "event_type": e.event_type, "occurred_at": e.occurred_at,
                      "red_flag_category": e.red_flag_category, "is_synthetic": e.is_synthetic}
                     for e in page["items"]]
    return page


# ---------------------------------------------------------------- learner inbox (in-app "delivery")

def _my_target(db, user: User) -> Target:
    t = db.scalar(select(Target).where(Target.user_id == user.id, Target.deleted_at.is_(None)))
    if not t:
        raise NotFound("No learner profile linked to this account")
    return t


@router.get("/inbox")
def inbox(principal: Learner, db: DB, _u: UserOnly):
    """Active/completed simulations that include the current learner (shown in-app only)."""
    t = _my_target(db, principal.user)
    camp_ids = db.scalars(select(SimulationEvent.campaign_id).where(
        SimulationEvent.target_id == t.id, SimulationEvent.event_type == "delivered_preview").distinct()).all()
    camps = db.scalars(select(Campaign).where(Campaign.id.in_(camp_ids), Campaign.org_id == principal.org_id,
                                              Campaign.deleted_at.is_(None))
                       .order_by(Campaign.started_at.desc())).all()
    events = db.execute(select(SimulationEvent.campaign_id, SimulationEvent.event_type).where(
        SimulationEvent.target_id == t.id)).all()
    done: dict[str, set[str]] = {}
    for cid, et in events:
        done.setdefault(cid, set()).add(et)
    return [{"campaign_id": c.id, "name": c.name, "subject": c.template.subject if c.template else "",
             "sender_name": c.template.sender_name if c.template else "", "started_at": c.started_at,
             "actions": sorted(done.get(c.id, set()))} for c in camps if c.template]


class InboxAction(BaseModel):
    action: Literal["previewed", "clicked_sim", "reported"]


@router.get("/inbox/{campaign_id}/preview")
def inbox_preview(campaign_id: str, principal: Learner, db: DB, _u: UserOnly):
    t = _my_target(db, principal.user)
    c = repo_for(principal, db).get(Campaign, campaign_id)
    if not db.scalar(select(SimulationEvent.id).where(SimulationEvent.campaign_id == c.id,
                                                      SimulationEvent.target_id == t.id)):
        raise NotFound("Campaign not found")
    preview = render_preview(c.template)
    my_actions = sorted(set(db.scalars(select(SimulationEvent.event_type).where(
        SimulationEvent.campaign_id == c.id, SimulationEvent.target_id == t.id)).all()))
    preview["my_actions"] = my_actions
    # Learners first see the lure WITHOUT the answer key; flags are revealed once they have acted.
    if not {"reported", "clicked_sim"} & set(my_actions):
        preview["red_flags_hidden"] = True
        preview["red_flags"] = []
    return preview


@router.post("/inbox/{campaign_id}/action")
def inbox_action(campaign_id: str, body: InboxAction, request: Request, principal: Learner, db: DB,
                 _u: UserOnly):
    t = _my_target(db, principal.user)
    c = repo_for(principal, db).get(Campaign, campaign_id)
    if not db.scalar(select(SimulationEvent.id).where(SimulationEvent.campaign_id == c.id,
                                                      SimulationEvent.target_id == t.id)):
        raise NotFound("Campaign not found")
    already = db.scalar(select(SimulationEvent.id).where(SimulationEvent.campaign_id == c.id,
                                                         SimulationEvent.target_id == t.id,
                                                         SimulationEvent.event_type == body.action))
    cat = None
    if body.action == "clicked_sim" and c.template and c.template.red_flags:
        cat = c.template.red_flags[0].get("category")
    if not already:
        db.add(SimulationEvent(org_id=principal.org_id, campaign_id=c.id, target_id=t.id,
                               department_id=t.department_id, event_type=body.action, occurred_at=utcnow(),
                               red_flag_category=cat, is_synthetic=False))
    enrollment = None
    if body.action == "clicked_sim":
        enrollment = auto_enroll_for_failure(db, principal.org_id, t.id, cat)
        if enrollment:
            notify(db, principal.org_id, principal.id, "training", "Training assigned",
                   f"You were enrolled in '{enrollment.module.title}'.", "/training")
    elif body.action == "reported" and not already:
        notify(db, principal.org_id, principal.id, "simulation", "Well spotted! 🎉",
               f"You correctly reported the simulation '{c.template.subject if c.template else c.name}'.",
               f"/inbox/{c.id}")
    audit_p(db, principal, request, f"inbox.{body.action}", "campaign", c.id)
    db.commit()
    cache.invalidate_org(principal.org_id)
    result: dict = {"recorded": not already, "red_flags": c.template.red_flags if c.template else []}
    if body.action == "clicked_sim":
        result["landing_page"] = build_landing_page(c.template.name, c.template.red_flags)
        result["enrolled_module"] = enrollment.module.title if enrollment else None
    elif body.action == "reported":
        result["message"] = "Well spotted! This was a training simulation. Reporting is exactly right."
    return result
