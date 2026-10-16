"""Admin: users & invites, API keys, webhooks, audit log, org settings, notifications."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import func, select, update

from app.api.deps import DB, ROLE_RANK, Admin, Learner, Paging, UserOnly, repo_for
from app.core.errors import AppError, Conflict, Forbidden
from app.core.security import generate_api_key, sha256
from app.db.base import utcnow
from app.db.models import (
    ApiKey,
    AuditLog,
    Invite,
    Notification,
    Organization,
    RefreshToken,
    User,
    Webhook,
    WebhookDelivery,
)
from app.schemas.auth import UserOut
from app.schemas.common import Message
from app.services.audit import audit_p
from app.services.exports import rows_to_csv
from app.workers import webhooks as wh

router = APIRouter(tags=["admin"])
API_SCOPES = ("analytics:read",)
WEBHOOK_EVENTS = ("campaign.activated", "campaign.completed", "report.submitted", "webhook.test")


def _assignable(principal, role: str) -> None:
    """Admins can't grant a role above their own (super_admin is never assignable via API)."""
    if role == "super_admin" or ROLE_RANK[role] > ROLE_RANK.get(principal.role, 0):
        raise Forbidden("You cannot assign this role")


# ---------------------------------------------------------------- users

@router.get("/admin/users")
def list_users(principal: Admin, db: DB, p: Paging,
               role: Annotated[str | None, Query(pattern="^(super_admin|org_admin|manager|learner)$")] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(User)
    if role:
        stmt = stmt.where(User.role == role)
    page = repo.paginate(stmt, User, page=p.page, page_size=p.page_size, sort=p.sort or "full_name",
                         order=p.order if p.sort else "asc", search=p.q, search_fields=("full_name", "email"),
                         sortable=("full_name", "email", "role", "created_at", "last_login_at"))
    page["items"] = [UserOut.model_validate(u).model_dump() for u in page["items"]]
    return page


class UserPatch(BaseModel):
    role: Literal["org_admin", "manager", "learner"] | None = None
    is_active: bool | None = None
    unlock: bool | None = None


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def patch_user(user_id: str, body: UserPatch, request: Request, principal: Admin, db: DB):
    u = repo_for(principal, db).get(User, user_id)
    if u.id == principal.id and (body.role or body.is_active is False):
        raise AppError("You cannot change your own role or deactivate yourself", code="self_change")
    if ROLE_RANK[u.role] > ROLE_RANK[principal.role]:
        raise Forbidden("Cannot modify a user with a higher role")
    if body.role:
        _assignable(principal, body.role)
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:  # kill their sessions
            db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id).values(revoked_at=utcnow()))
    if body.unlock:
        u.locked_until, u.failed_logins = None, 0
    audit_p(db, principal, request, "user.updated", "user", u.id, **body.model_dump(exclude_none=True))
    db.commit()
    return u


@router.delete("/admin/users/{user_id}", response_model=Message)
def delete_user(user_id: str, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    u = repo.get(User, user_id)
    if u.id == principal.id:
        raise AppError("You cannot delete yourself", code="self_change")
    if ROLE_RANK[u.role] > ROLE_RANK[principal.role]:
        raise Forbidden("Cannot delete a user with a higher role")
    repo.soft_delete(u)
    u.is_active = False
    db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id).values(revoked_at=utcnow()))
    audit_p(db, principal, request, "user.deleted", "user", u.id)
    db.commit()
    return {"message": "User deleted"}


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["org_admin", "manager", "learner"] = "learner"


@router.post("/admin/invites", status_code=201)
def create_invite(body: InviteIn, request: Request, principal: Admin, db: DB):
    """Creates an in-app invite CODE shown once to the admin. No email is sent."""
    _assignable(principal, body.role)
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise Conflict("A user with this email already exists")
    code = secrets.token_urlsafe(18)
    inv = repo_for(principal, db).add(Invite, code_hash=sha256(code), email=body.email.lower(), role=body.role,
                                      expires_at=utcnow() + timedelta(days=7))
    audit_p(db, principal, request, "invite.created", "invite", inv.id, email=inv.email, role=inv.role)
    db.commit()
    return {"id": inv.id, "code": code, "email": inv.email, "role": inv.role, "expires_at": inv.expires_at,
            "note": "Share this code in person or via your own channel. It is shown only once."}


@router.get("/admin/invites")
def list_invites(principal: Admin, db: DB, p: Paging):
    repo = repo_for(principal, db)
    page = repo.paginate(repo.query(Invite), Invite, page=p.page, page_size=p.page_size, sort=p.sort,
                         order=p.order, search=p.q, search_fields=("email",), sortable=("created_at", "email"))
    page["items"] = [{"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at,
                      "used_at": i.used_at, "created_at": i.created_at} for i in page["items"]]
    return page


@router.delete("/admin/invites/{invite_id}", response_model=Message)
def revoke_invite(invite_id: str, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    inv = repo.get(Invite, invite_id)
    repo.soft_delete(inv)
    audit_p(db, principal, request, "invite.revoked", "invite", inv.id)
    db.commit()
    return {"message": "Invite revoked"}


# ---------------------------------------------------------------- API keys

class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scopes: list[Literal["analytics:read"]] = Field(min_length=1)


def key_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "created_at": k.created_at,
            "last_used_at": k.last_used_at, "revoked_at": k.revoked_at}


@router.get("/admin/api-keys")
def list_keys(principal: Admin, db: DB, p: Paging):
    repo = repo_for(principal, db)
    page = repo.paginate(repo.query(ApiKey), ApiKey, page=p.page, page_size=p.page_size, sort=p.sort,
                         order=p.order, search=p.q, search_fields=("name",), sortable=("created_at", "name"))
    page["items"] = [key_out(k) for k in page["items"]]
    return page


@router.post("/admin/api-keys", status_code=201)
def create_key(body: ApiKeyIn, request: Request, principal: Admin, db: DB, _u: UserOnly):
    raw, prefix, digest = generate_api_key()
    k = repo_for(principal, db).add(ApiKey, name=body.name, prefix=prefix, key_hash=digest,
                                    scopes=list(dict.fromkeys(body.scopes)), created_by=principal.id)
    audit_p(db, principal, request, "api_key.created", "api_key", k.id, scopes=k.scopes)
    db.commit()
    return {**key_out(k), "key": raw, "note": "Copy this key now. Only its SHA-256 hash is stored."}


@router.delete("/admin/api-keys/{key_id}", response_model=Message)
def revoke_key(key_id: str, request: Request, principal: Admin, db: DB):
    k = repo_for(principal, db).get(ApiKey, key_id)
    k.revoked_at = utcnow()
    audit_p(db, principal, request, "api_key.revoked", "api_key", k.id)
    db.commit()
    return {"message": "API key revoked"}


# ---------------------------------------------------------------- webhooks

class WebhookIn(BaseModel):
    url: HttpUrl
    events: list[Literal["campaign.activated", "campaign.completed", "report.submitted", "webhook.test", "*"]] = \
        Field(default_factory=lambda: ["*"], min_length=1)


def hook_out(h: Webhook) -> dict:
    return {"id": h.id, "url": h.url, "events": h.events, "is_active": h.is_active, "created_at": h.created_at,
            "secret_preview": h.secret[:6] + "…"}


@router.get("/admin/webhooks")
def list_webhooks(principal: Admin, db: DB, p: Paging):
    repo = repo_for(principal, db)
    page = repo.paginate(repo.query(Webhook), Webhook, page=p.page, page_size=p.page_size, sort=p.sort,
                         order=p.order, search=p.q, search_fields=("url",), sortable=("created_at", "url"))
    page["items"] = [hook_out(h) for h in page["items"]]
    return page


@router.post("/admin/webhooks", status_code=201)
def create_webhook(body: WebhookIn, request: Request, principal: Admin, db: DB):
    err = wh.validate_webhook_url(str(body.url))
    if err:
        raise AppError(err, code="invalid_webhook_url", status_code=422)
    secret = "whsec_" + secrets.token_urlsafe(24)
    h = repo_for(principal, db).add(Webhook, url=str(body.url), secret=secret, events=body.events)
    audit_p(db, principal, request, "webhook.created", "webhook", h.id, url=h.url)
    db.commit()
    return {**hook_out(h), "secret": secret, "note": "Store this signing secret now; it is shown once."}


@router.patch("/admin/webhooks/{hook_id}")
def toggle_webhook(hook_id: str, request: Request, principal: Admin, db: DB,
                   is_active: Annotated[bool, Query()]):
    h = repo_for(principal, db).get(Webhook, hook_id)
    h.is_active = is_active
    audit_p(db, principal, request, "webhook.updated", "webhook", h.id, is_active=is_active)
    db.commit()
    return hook_out(h)


@router.delete("/admin/webhooks/{hook_id}", response_model=Message)
def delete_webhook(hook_id: str, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    h = repo.get(Webhook, hook_id)
    repo.soft_delete(h)
    audit_p(db, principal, request, "webhook.deleted", "webhook", h.id)
    db.commit()
    return {"message": "Webhook deleted"}


@router.post("/admin/webhooks/{hook_id}/test")
def test_webhook(hook_id: str, request: Request, principal: Admin, db: DB, background: BackgroundTasks):
    h = repo_for(principal, db).get(Webhook, hook_id)
    d = WebhookDelivery(org_id=principal.org_id, webhook_id=h.id, event="webhook.test",
                        payload={"message": "Test delivery from PhishGuard"})
    db.add(d)
    audit_p(db, principal, request, "webhook.test", "webhook", h.id)
    db.commit()
    background.add_task(wh.deliver, [d.id])
    return {"delivery_id": d.id, "message": "Test delivery queued"}


@router.get("/admin/webhooks/{hook_id}/deliveries")
def webhook_deliveries(hook_id: str, principal: Admin, db: DB, p: Paging):
    repo = repo_for(principal, db)
    repo.get(Webhook, hook_id)
    page = repo.paginate(repo.query(WebhookDelivery).where(WebhookDelivery.webhook_id == hook_id),
                         WebhookDelivery, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         sortable=("created_at", "status"))
    page["items"] = [{"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts,
                      "response_code": d.response_code, "last_error": d.last_error, "created_at": d.created_at}
                     for d in page["items"]]
    return page


# ---------------------------------------------------------------- audit log

def _audit_stmt(repo, action, actor, date_from, date_to):
    stmt = repo.query(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor:
        stmt = stmt.where(func.lower(AuditLog.actor_email).like(f"%{actor.lower()}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    return stmt


def audit_row(a: AuditLog) -> dict:
    return {"id": a.id, "created_at": a.created_at, "actor_email": a.actor_email, "action": a.action,
            "entity_type": a.entity_type, "entity_id": a.entity_id, "ip": a.ip, "request_id": a.request_id,
            "details": a.details}


@router.get("/admin/audit")
def audit_log(principal: Admin, db: DB, p: Paging, action: Annotated[str | None, Query(max_length=60)] = None,
              actor: Annotated[str | None, Query(max_length=120)] = None, date_from: datetime | None = None,
              date_to: datetime | None = None):
    repo = repo_for(principal, db)
    page = repo.paginate(_audit_stmt(repo, action, actor, date_from, date_to), AuditLog, page=p.page,
                         page_size=p.page_size, sort=p.sort, order=p.order, sortable=("created_at", "action"))
    page["items"] = [audit_row(a) for a in page["items"]]
    return page


@router.get("/admin/audit/export.csv")
def audit_export(request: Request, principal: Admin, db: DB,
                 action: Annotated[str | None, Query(max_length=60)] = None,
                 actor: Annotated[str | None, Query(max_length=120)] = None,
                 date_from: datetime | None = None, date_to: datetime | None = None):
    repo = repo_for(principal, db)
    rows = db.scalars(_audit_stmt(repo, action, actor, date_from, date_to)
                      .order_by(AuditLog.created_at.desc()).limit(10_000)).all()
    audit_p(db, principal, request, "audit.exported", "audit_log", None, rows=len(rows))
    db.commit()
    csv_rows = [{**audit_row(a), "details": str(a.details)} for a in rows]
    return Response(rows_to_csv(csv_rows, ["created_at", "actor_email", "action", "entity_type", "entity_id",
                                           "ip", "request_id", "details"]), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="phishguard-audit.csv"'})


# ---------------------------------------------------------------- org settings

class OrgSettingsIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    leaderboard_individuals_enabled: bool | None = None
    risk_high_threshold: int | None = Field(default=None, ge=30, le=95)
    training_pass_mark_default: int | None = Field(default=None, ge=1, le=100)


@router.get("/admin/settings")
def get_settings_ep(principal: Admin, db: DB):
    org = db.get(Organization, principal.org_id)
    return {"id": org.id, "name": org.name, "slug": org.slug, "settings": org.settings or {}}


@router.patch("/admin/settings")
def patch_settings(body: OrgSettingsIn, request: Request, principal: Admin, db: DB):
    org = db.get(Organization, principal.org_id)
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        org.name = changes.pop("name")
    org.settings = {**(org.settings or {}), **changes}
    audit_p(db, principal, request, "org.settings_updated", "organization", org.id, **body.model_dump(exclude_none=True))
    db.commit()
    return {"id": org.id, "name": org.name, "slug": org.slug, "settings": org.settings}


@router.get("/admin/organizations")
def list_orgs(principal: Admin, db: DB):
    """super_admin sees all organizations (names only); others see their own."""
    stmt = select(Organization) if principal.role == "super_admin" else select(Organization).where(
        Organization.id == principal.org_id)
    return [{"id": o.id, "name": o.name, "slug": o.slug} for o in db.scalars(stmt).all()]


# ---------------------------------------------------------------- notifications (every user)

@router.get("/notifications")
def notifications(principal: Learner, db: DB, _u: UserOnly, p: Paging,
                  unread: Annotated[bool, Query()] = False):
    repo = repo_for(principal, db)
    stmt = repo.query(Notification).where(Notification.user_id == principal.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    page = repo.paginate(stmt, Notification, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         sortable=("created_at",))
    page["items"] = [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
                      "read_at": n.read_at, "created_at": n.created_at} for n in page["items"]]
    page["unread"] = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == principal.id, Notification.read_at.is_(None))) or 0
    return page


@router.post("/notifications/read-all", response_model=Message)
def read_all(principal: Learner, db: DB, _u: UserOnly):
    db.execute(update(Notification).where(Notification.user_id == principal.id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()
    return {"message": "All notifications marked read"}


@router.post("/notifications/{notification_id}/read", response_model=Message)
def read_one(notification_id: str, principal: Learner, db: DB, _u: UserOnly):
    n = repo_for(principal, db).get(Notification, notification_id)
    if n.user_id != principal.id:
        raise AppError("Notification not found", code="not_found", status_code=404)
    n.read_at = utcnow()
    db.commit()
    return {"message": "Marked read"}


_ = (API_SCOPES, WEBHOOK_EVENTS)
