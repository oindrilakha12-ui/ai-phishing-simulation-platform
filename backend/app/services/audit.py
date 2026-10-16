"""Audit logging: who did what, to which entity, when, and from which IP."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import request_id_ctx
from app.core.ratelimit import client_ip
from app.db.models import AuditLog


def audit(db: Session, *, org_id: str, action: str, entity_type: str, entity_id: str | None = None,
          actor_id: str | None = None, actor_email: str | None = None, request: Request | None = None,
          details: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(
        org_id=org_id, actor_id=actor_id, actor_email=actor_email, action=action,
        entity_type=entity_type, entity_id=entity_id,
        ip=client_ip(request) if request else None, request_id=request_id_ctx.get(),
        details=details or {},
    ))


def audit_p(db: Session, principal, request: Request, action: str, entity_type: str,
            entity_id: str | None = None, **details: Any) -> None:
    """Shortcut used by routers: audit an action performed by the current principal."""
    audit(db, org_id=principal.org_id, action=action, entity_type=entity_type, entity_id=entity_id,
          actor_id=principal.id, actor_email=principal.email, request=request, details=details)
