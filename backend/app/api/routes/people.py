"""Departments and synthetic targets (learners)."""
from __future__ import annotations

from typing import Annotated

from faker import Faker
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, Admin, Manager, Paging, repo_for
from app.core.errors import Conflict
from app.db.models import Department, Enrollment, SimulationEvent, Target
from app.schemas.common import Message, Page
from app.schemas.domain import DepartmentIn, DepartmentOut, TargetOut
from app.services.audit import audit_p
from app.services.risk import compute_target_scores

router = APIRouter(tags=["people"])


@router.get("/departments", response_model=Page[DepartmentOut])
def list_departments(principal: Manager, db: DB, p: Paging):
    repo = repo_for(principal, db)
    return repo.paginate(repo.query(Department), Department, page=p.page, page_size=p.page_size,
                         sort=p.sort or "name", order=p.order if p.sort else "asc", search=p.q,
                         search_fields=("name",), sortable=("name", "created_at"))


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentIn, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    if db.scalar(repo.query(Department).where(func.lower(Department.name) == body.name.lower())):
        raise Conflict("A department with this name already exists")
    d = repo.add(Department, name=body.name)
    audit_p(db, principal, request, "department.created", "department", d.id, name=d.name)
    db.commit()
    return d


@router.patch("/departments/{dept_id}", response_model=DepartmentOut)
def rename_department(dept_id: str, body: DepartmentIn, request: Request, principal: Admin, db: DB):
    d = repo_for(principal, db).get(Department, dept_id)
    old = d.name
    d.name = body.name
    audit_p(db, principal, request, "department.renamed", "department", d.id, old=old, new=body.name)
    db.commit()
    return d


@router.delete("/departments/{dept_id}", response_model=Message)
def delete_department(dept_id: str, request: Request, principal: Admin, db: DB):
    repo = repo_for(principal, db)
    d = repo.get(Department, dept_id)
    if db.scalar(select(func.count()).select_from(Target).where(Target.department_id == d.id,
                                                                Target.deleted_at.is_(None))):
        raise Conflict("Department still has people; move them first")
    repo.soft_delete(d)
    audit_p(db, principal, request, "department.deleted", "department", d.id)
    db.commit()
    return {"message": "Department deleted"}


def _target_out(t: Target) -> dict:
    data = TargetOut.model_validate(t).model_dump()
    data["department_name"] = t.department.name if t.department else None
    return data


@router.get("/targets", response_model=Page[TargetOut])
def list_targets(principal: Manager, db: DB, p: Paging,
                 department_id: Annotated[str | None, Query(max_length=32)] = None):
    repo = repo_for(principal, db)
    stmt = repo.query(Target)
    if department_id:
        stmt = stmt.where(Target.department_id == department_id)
    page = repo.paginate(stmt, Target, page=p.page, page_size=p.page_size, sort=p.sort or "full_name",
                         order=p.order if p.sort else "asc", search=p.q, search_fields=("full_name", "email"),
                         sortable=("full_name", "email", "created_at"))
    page["items"] = [_target_out(t) for t in page["items"]]
    return page


@router.get("/targets/{target_id}")
def get_target(target_id: str, principal: Manager, db: DB):
    repo = repo_for(principal, db)
    t = repo.get(Target, target_id)
    counts = dict(db.execute(select(SimulationEvent.event_type, func.count()).where(
        SimulationEvent.org_id == principal.org_id, SimulationEvent.target_id == t.id)
        .group_by(SimulationEvent.event_type)).all())
    enrollments = db.scalars(repo.query(Enrollment).where(Enrollment.target_id == t.id)).all()
    risk = compute_target_scores(db, principal.org_id).get(t.id)
    return {**_target_out(t), "event_counts": counts, "risk": risk,
            "enrollments": [{"id": e.id, "module": e.module.title, "status": e.status, "source": e.source}
                            for e in enrollments]}


class SyntheticIn(BaseModel):
    department_id: str = Field(max_length=32)
    count: int = Field(ge=1, le=100)


@router.post("/targets/generate-synthetic", response_model=Message, status_code=201)
def generate_synthetic(body: SyntheticIn, request: Request, principal: Admin, db: DB):
    """Add SYNTHETIC people (Faker). There is deliberately no real-contact import."""
    repo = repo_for(principal, db)
    dept = repo.get(Department, body.department_id)
    fake = Faker()
    for _ in range(body.count):
        name = fake.name()
        handle = name.lower().replace(" ", ".").replace("'", "")
        repo.add(Target, full_name=name, email=f"{handle}.{fake.random_int(100, 999)}@people.example",
                 department_id=dept.id, is_synthetic=True)
    audit_p(db, principal, request, "targets.synthetic_generated", "department", dept.id, count=body.count)
    db.commit()
    return {"message": f"Created {body.count} synthetic people in {dept.name}"}
