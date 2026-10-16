"""Authentication, RBAC and tenant dependencies shared by every router.

Three ways to authenticate:
  1. httpOnly cookie `pg_access` (browser) — mutating requests must also send the CSRF header.
  2. `Authorization: Bearer <access JWT>` (scripts/tests) — no CSRF needed (not ambient).
  3. `X-API-Key: pg_...` — read-only, scope-checked (integrations).
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token, sha256
from app.db.base import utcnow
from app.db.models import ApiKey, RevokedToken, User
from app.db.repository import TenantRepo
from app.db.session import get_db

ACCESS_COOKIE = "pg_access"
REFRESH_COOKIE = "pg_refresh"
CSRF_COOKIE = "pg_csrf"
CSRF_HEADER = "x-csrf-token"
ROLE_RANK = {"learner": 1, "manager": 2, "org_admin": 3, "super_admin": 4}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    org_id: str
    role: str
    via: str  # cookie | bearer | api_key
    user: User | None = None
    api_key: ApiKey | None = None
    scopes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def email(self) -> str | None:
        return self.user.email if self.user else f"api_key:{self.api_key.prefix}" if self.api_key else None


def _user_from_access_token(db: Session, token: str) -> User:
    try:
        claims = decode_token(token, "access")
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Access token expired", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid access token")
    if db.scalar(select(RevokedToken.id).where(RevokedToken.jti == claims["jti"])):
        raise Unauthorized("Token has been revoked", code="token_revoked")
    user = db.get(User, claims["sub"])
    if not user or not user.is_active or user.deleted_at is not None or user.org_id != claims.get("org"):
        raise Unauthorized("User no longer active")
    return user


def get_principal(request: Request, db: DB) -> Principal:
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key")

    if api_key:
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256(api_key)))
        if not key or key.revoked_at or key.deleted_at:
            raise Unauthorized("Invalid API key")
        key.last_used_at = utcnow()
        db.commit()
        return Principal(org_id=key.org_id, role="api_key", via="api_key", api_key=key, scopes=key.scopes)

    if auth.lower().startswith("bearer "):
        user = _user_from_access_token(db, auth[7:].strip())
        return Principal(org_id=user.org_id, role=user.role, via="bearer", user=user)

    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise Unauthorized("Not authenticated")
    user = _user_from_access_token(db, token)
    # CSRF: double-submit cookie. Cookies are sent automatically by the browser, so a
    # cross-site form could ride on them; requiring a header the attacker can't read stops that.
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not hmac.compare_digest(header, cookie):
            raise Forbidden("Missing or invalid CSRF token", code="csrf_failed")
    return Principal(org_id=user.org_id, role=user.role, via="cookie", user=user)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(min_role: str, api_scope: str | None = None):
    """RBAC guard. API keys pass only for read requests on endpoints that declare a matching scope."""

    def _dep(request: Request, principal: CurrentPrincipal) -> Principal:
        if principal.via == "api_key":
            if api_scope and api_scope in principal.scopes and request.method in SAFE_METHODS:
                return principal
            raise Forbidden("API key lacks the required scope")
        if ROLE_RANK.get(principal.role, 0) < ROLE_RANK[min_role]:
            raise Forbidden(f"Requires role {min_role} or higher")
        return principal

    return _dep


def user_principal(principal: CurrentPrincipal) -> Principal:
    """For endpoints that only make sense for a human user (not an API key)."""
    if principal.user is None:
        raise Forbidden("This endpoint requires a user session")
    return principal


Learner = Annotated[Principal, Depends(require_role("learner"))]
Manager = Annotated[Principal, Depends(require_role("manager"))]
Admin = Annotated[Principal, Depends(require_role("org_admin"))]
UserOnly = Annotated[Principal, Depends(user_principal)]


def repo_for(principal: Principal, db: Session) -> TenantRepo:
    return TenantRepo(db, principal.org_id)


class ListParams:
    """Standard pagination/sort/search query parameters for every list endpoint."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 20,
        sort: Annotated[str | None, Query(max_length=40)] = None,
        order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
        q: Annotated[str | None, Query(max_length=100)] = None,
    ):
        self.page, self.page_size, self.sort, self.order, self.q = page, page_size, sort, order, q


Paging = Annotated[ListParams, Depends()]
