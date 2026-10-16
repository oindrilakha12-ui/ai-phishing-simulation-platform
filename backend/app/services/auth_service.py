"""Session issuing, refresh rotation and revocation."""
from __future__ import annotations

from datetime import timedelta

import jwt
from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.security import create_token, decode_token, new_csrf_token
from app.db.base import new_id, utcnow
from app.db.models import Organization, RefreshToken, RevokedToken, User
from app.services.audit import audit

ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE = "pg_access", "pg_refresh", "pg_csrf"


def _set_cookie(response: Response, name: str, value: str, max_age: int, http_only: bool, path: str = "/"):
    s = get_settings()
    response.set_cookie(name, value, max_age=max_age, httponly=http_only, secure=s.cookie_secure,
                        samesite=s.cookie_samesite, path=path)


def issue_session(db: Session, response: Response, user: User, family: str | None = None) -> dict:
    """Create access+refresh tokens, persist the refresh token, set cookies."""
    s = get_settings()
    access, _, _ = create_token(subject=user.id, org_id=user.org_id, role=user.role, token_type="access")
    family = family or new_id()
    refresh, r_jti, r_exp = create_token(subject=user.id, org_id=user.org_id, role=user.role,
                                         token_type="refresh", family=family)
    db.add(RefreshToken(jti=r_jti, family=family, user_id=user.id, expires_at=r_exp))
    csrf = new_csrf_token()
    _set_cookie(response, ACCESS_COOKIE, access, s.access_token_minutes * 60, True)
    _set_cookie(response, REFRESH_COOKIE, refresh, s.refresh_token_days * 86400, True, path="/api/v1/auth")
    _set_cookie(response, CSRF_COOKIE, csrf, s.refresh_token_days * 86400, False)
    return {"access_token": access, "refresh_token": refresh, "csrf_token": csrf}


def session_payload(db: Session, user: User, tokens: dict, include_token: bool) -> dict:
    org = db.get(Organization, user.org_id)
    return {
        "user": user,
        "org_name": org.name if org else "",
        "csrf_token": tokens["csrf_token"],
        "access_token": tokens["access_token"] if include_token else None,
        "demo_mode": get_settings().demo_mode,
    }


def rotate_refresh(db: Session, response: Response, request: Request, raw_refresh: str) -> tuple[User, dict]:
    try:
        claims = decode_token(raw_refresh, "refresh")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid refresh token")
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == claims["jti"]))
    if stored is None:
        raise Unauthorized("Unknown refresh token")
    user = db.get(User, stored.user_id)
    if stored.revoked_at is not None:
        # Reuse of a rotated token => likely theft. Kill the whole family.
        db.execute(update(RefreshToken).where(RefreshToken.family == stored.family)
                   .values(revoked_at=utcnow()))
        if user:
            audit(db, org_id=user.org_id, action="auth.refresh_reuse_detected", entity_type="user",
                  entity_id=user.id, actor_id=user.id, actor_email=user.email, request=request)
        db.commit()
        raise Unauthorized("Refresh token reuse detected; please sign in again", code="refresh_reuse")
    if not user or not user.is_active or user.deleted_at:
        raise Unauthorized("User no longer active")
    stored.revoked_at = utcnow()
    tokens = issue_session(db, response, user, family=stored.family)
    db.commit()
    return user, tokens


def revoke_session(db: Session, response: Response, access_jti: str | None, access_exp,
                   raw_refresh: str | None) -> None:
    if access_jti:
        db.add(RevokedToken(jti=access_jti, expires_at=access_exp))
    if raw_refresh:
        try:
            claims = decode_token(raw_refresh, "refresh")
            db.execute(update(RefreshToken).where(RefreshToken.family == claims.get("fam"))
                       .values(revoked_at=utcnow()))
        except jwt.InvalidTokenError:
            pass
    db.commit()
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/v1/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path)


def lockout_until():
    return utcnow() + timedelta(minutes=get_settings().lockout_minutes)
