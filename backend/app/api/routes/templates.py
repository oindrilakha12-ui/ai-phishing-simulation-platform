"""Lure templates (fictional brands, watermarked, always with red flags) + preview sandbox."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import DB, Learner, Manager, Paging, repo_for
from app.core.errors import AppError
from app.db.models import Template, TemplateVersion
from app.schemas.common import Message, Page
from app.schemas.domain import (
    RED_FLAG_CATEGORIES,
    PreviewOut,
    TemplateIn,
    TemplateOut,
    TemplateUpdate,
    TemplateVersionOut,
)
from app.services.audit import audit_p
from app.services.safety import (
    FICTIONAL_BRANDS,
    PREVIEW_CSP,
    WATERMARK,
    build_landing_page,
    build_preview_document,
    ensure_watermark,
    validate_lure,
)

router = APIRouter(prefix="/templates", tags=["templates"])

SNAPSHOT_FIELDS = ("name", "brand", "category", "difficulty", "subject", "sender_name", "sender_email",
                   "body_html", "red_flags")


def _check_safe(data: dict) -> None:
    problems = validate_lure(data)
    if problems:
        raise AppError("Template violates the safety scope", code="unsafe_template", status_code=422,
                       details=problems)


@router.get("/meta")
def template_meta(_: Learner):
    return {"fictional_brands": sorted(FICTIONAL_BRANDS), "red_flag_categories": RED_FLAG_CATEGORIES,
            "watermark": WATERMARK, "difficulties": ["easy", "medium", "hard"]}


@router.get("", response_model=Page[TemplateOut])
def list_templates(principal: Manager, db: DB, p: Paging,
                   difficulty: Annotated[str | None, Query(pattern="^(easy|medium|hard)$")] = None,
                   category: Annotated[str | None, Query(max_length=40)] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(Template)
    if difficulty:
        stmt = stmt.where(Template.difficulty == difficulty)
    if category:
        stmt = stmt.where(Template.category == category)
    return repo.paginate(stmt, Template, page=p.page, page_size=p.page_size, sort=p.sort, order=p.order,
                         search=p.q, search_fields=("name", "subject", "brand"),
                         sortable=("created_at", "name", "difficulty", "updated_at"))


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, request: Request, principal: Manager, db: DB, source: str = "manual"):
    data = body.model_dump()
    data["body_html"] = ensure_watermark(data["body_html"])
    _check_safe(data)
    repo = repo_for(principal, db)
    t = repo.add(Template, **data, version=1, source=source if source in ("manual", "ai_demo", "ai") else "manual")
    repo.add(TemplateVersion, template_id=t.id, version=1, snapshot=data, changed_by=principal.id)
    audit_p(db, principal, request, "template.created", "template", t.id, name=t.name, source=t.source)
    db.commit()
    return t


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: str, principal: Manager, db: DB):
    return repo_for(principal, db).get(Template, template_id)


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(template_id: str, body: TemplateUpdate, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    t = repo.get(Template, template_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return t
    merged = {f: getattr(t, f) for f in SNAPSHOT_FIELDS} | changes
    merged["body_html"] = ensure_watermark(merged["body_html"])
    _check_safe(merged)
    for k, v in merged.items():
        setattr(t, k, v)
    t.version += 1
    repo.add(TemplateVersion, template_id=t.id, version=t.version, snapshot=merged, changed_by=principal.id)
    audit_p(db, principal, request, "template.updated", "template", t.id, fields=sorted(changes), version=t.version)
    db.commit()
    return t


@router.delete("/{template_id}", response_model=Message)
def delete_template(template_id: str, request: Request, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    t = repo.get(Template, template_id)
    repo.soft_delete(t)
    audit_p(db, principal, request, "template.deleted", "template", t.id)
    db.commit()
    return {"message": "Template deleted"}


@router.get("/{template_id}/versions", response_model=list[TemplateVersionOut])
def template_versions(template_id: str, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    repo.get(Template, template_id)
    return db.scalars(repo.query(TemplateVersion).where(TemplateVersion.template_id == template_id)
                      .order_by(TemplateVersion.version.desc())).all()


@router.get("/{template_id}/preview", response_model=PreviewOut)
def preview_template(template_id: str, principal: Manager, db: DB):
    t = repo_for(principal, db).get(Template, template_id)
    return render_preview(t)


def render_preview(t: Template) -> dict:
    doc, links = build_preview_document(t.subject, t.sender_name, t.sender_email, t.body_html, t.red_flags)
    return {"template_id": t.id, "document": doc, "red_flags": t.red_flags, "links": links,
            "landing_page": build_landing_page(t.name, t.red_flags), "watermark": WATERMARK, "csp": PREVIEW_CSP}
