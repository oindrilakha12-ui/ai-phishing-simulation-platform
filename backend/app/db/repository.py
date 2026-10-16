"""Tenant-scoped data access.

`TenantRepo(db, org_id)` is the ONLY way route handlers read/write tenant tables. Every
query it builds is filtered by `org_id` and excludes soft-deleted rows, so a handler
cannot accidentally leak another organization's data. Tests in tests/test_tenant_isolation.py
prove this for every list/detail endpoint.
"""
from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.db.base import utcnow

M = TypeVar("M")


class TenantRepo:
    def __init__(self, db: Session, org_id: str):
        if not org_id:
            raise ValueError("TenantRepo requires an org_id")
        self.db = db
        self.org_id = org_id

    # ------------------------------------------------------------ queries
    def query(self, model: type[M], *, include_deleted: bool = False) -> Select:
        stmt = select(model).where(model.org_id == self.org_id)  # type: ignore[attr-defined]
        if not include_deleted and hasattr(model, "deleted_at"):
            stmt = stmt.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    def get(self, model: type[M], obj_id: str) -> M:
        obj = self.db.scalars(self.query(model).where(model.id == obj_id)).first()  # type: ignore[attr-defined]
        if obj is None:
            # Same 404 whether the row doesn't exist or belongs to another org (no existence oracle).
            raise NotFound(f"{model.__name__} not found")
        return obj

    def add(self, model: type[M], **fields: Any) -> M:
        fields.pop("org_id", None)  # callers can never choose the tenant
        obj = model(org_id=self.org_id, **fields)  # type: ignore[call-arg]
        self.db.add(obj)
        self.db.flush()
        return obj

    def soft_delete(self, obj: Any) -> None:
        if obj.org_id != self.org_id:
            raise NotFound("not found")
        obj.deleted_at = utcnow()

    # ------------------------------------------------------------ list helper
    def paginate(self, stmt: Select, model: Any, *, page: int, page_size: int, sort: str | None,
                 order: str, search: str | None = None, search_fields: tuple[str, ...] = (),
                 sortable: tuple[str, ...] = ("created_at",)) -> dict[str, Any]:
        """Apply search, sort and pagination and return the standard list envelope."""
        if search and search_fields:
            like = f"%{search.lower()}%"
            stmt = stmt.where(or_(*[func.lower(getattr(model, f)).like(like) for f in search_fields]))
        sort = sort or "created_at"
        if sort not in sortable:
            raise AppError(f"Cannot sort by '{sort}'. Allowed: {', '.join(sortable)}", code="invalid_sort")
        col = getattr(model, sort)
        stmt = stmt.order_by(desc(col) if order == "desc" else asc(col), model.id)
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = self.db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
        return {"items": items, "total": total, "page": page, "page_size": page_size}
