from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

import pyotp
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import CSRF_COOKIE, CSRF_HEADER, DB, REFRESH_COOKIE, UserOnly, get_principal
from app.core.config import get_settings
from app.core.errors import AppError, Forbidden, NotFound, Unauthorized
from app.core.ratelimit import rate_limit
from app.core.security import DUMMY_HASH, decode_token, hash_password, sha256, verify_password
from app.db.base import utcnow
from app.db.models import Invite, Target, User
from app.schemas.auth import InviteAccept, LoginIn, PasswordChange, SessionOut, TotpSetupOut, TotpVerifyIn, UserOut
from app.schemas.common import Message
from app.services.audit import audit, audit_p
from app.services.auth_service import issue_session, lockout_until, revoke_session, rotate_refresh, session_payload
from app.services.oidc import PROVIDERS, MockOIDCProvider

router = APIRouter(prefix="/auth", tags=["auth"])
AuthLimit = Depends(rate_limit("auth", "rate_limit_auth"))


def _check_csrf(request: Request) -> None:
    header, cookie = request.headers.get(CSRF_HEADER, ""), request.cookies.get(CSRF_COOKIE, "")
    if not header or not secrets.compare_digest(header, cookie):
        raise Forbidden("Missing or invalid CSRF token", code="csrf_failed")


@router.post("/login", response_model=SessionOut, dependencies=[AuthLimit])
def login(body: LoginIn, request: Request, response: Response, db: DB,
          include_token: Annotated[bool, Query()] = False):
    user = db.scalar(select(User).where(User.email == body.email.lower(), User.deleted_at.is_(None)))
    if user is None:
        verify_password(body.password, DUMMY_HASH)  # equalise timing; don't reveal unknown emails
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise AppError("Account temporarily locked after repeated failures. Try again later.",
                       code="account_locked", status_code=423,
                       details={"locked_until": user.locked_until.isoformat()})

    def _fail(reason: str):
        user.failed_logins += 1
        if user.failed_logins >= get_settings().max_failed_logins:
            user.locked_until = lockout_until()
            user.failed_logins = 0
            audit(db, org_id=user.org_id, action="auth.locked", entity_type="user", entity_id=user.id,
                  actor_email=user.email, request=request)
        audit(db, org_id=user.org_id, action="auth.login_failed", entity_type="user", entity_id=user.id,
              actor_email=user.email, request=request, details={"reason": reason})
        db.commit()

    if not verify_password(body.password, user.password_hash) or not user.is_active:
        _fail("bad_password")
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    if user.totp_enabled:
        if not body.totp_code:
            raise Unauthorized("Two-factor code required", code="totp_required")
        if not pyotp.TOTP(user.totp_secret or "").verify(body.totp_code, valid_window=1):
            _fail("bad_totp")
            raise Unauthorized("Invalid two-factor code", code="invalid_totp")

    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    tokens = issue_session(db, response, user)
    audit(db, org_id=user.org_id, action="auth.login", entity_type="user", entity_id=user.id,
          actor_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return session_payload(db, user, tokens, include_token)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


@router.post("/refresh", response_model=SessionOut, dependencies=[AuthLimit])
def refresh(request: Request, response: Response, db: DB, body: RefreshIn | None = Body(default=None),
            include_token: Annotated[bool, Query()] = False):
    raw = body.refresh_token if body and body.refresh_token else None
    if raw is None:
        raw = request.cookies.get(REFRESH_COOKIE)
        if not raw:
            raise Unauthorized("No refresh token")
        _check_csrf(request)
    user, tokens = rotate_refresh(db, response, request, raw)
    return session_payload(db, user, tokens, include_token)


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, db: DB):
    access = request.cookies.get("pg_access") or request.headers.get("authorization", "")[7:]
    jti, exp = None, None
    if access:
        try:
            claims = decode_token(access, "access")
            jti, exp = claims["jti"], datetime.fromtimestamp(claims["exp"], UTC)
            user = db.get(User, claims["sub"])
            if user:
                audit(db, org_id=user.org_id, action="auth.logout", entity_type="user", entity_id=user.id,
                      actor_id=user.id, actor_email=user.email, request=request)
        except Exception:  # noqa: BLE001 - logout must always succeed
            pass
    revoke_session(db, response, jti, exp, request.cookies.get(REFRESH_COOKIE))
    return {"message": "Signed out"}


@router.get("/me", response_model=UserOut)
def me(principal: UserOnly):
    return principal.user


@router.post("/password", response_model=Message)
def change_password(body: PasswordChange, request: Request, principal: UserOnly, db: DB):
    user = principal.user
    if not verify_password(body.current_password, user.password_hash):
        raise Unauthorized("Current password is incorrect", code="invalid_credentials")
    user.password_hash = hash_password(body.new_password)
    audit_p(db, principal, request, "auth.password_changed", "user", user.id)
    db.commit()
    return {"message": "Password updated"}


# ---------------------------------------------------------------- TOTP 2FA

@router.post("/2fa/setup", response_model=TotpSetupOut)
def totp_setup(principal: UserOnly, db: DB):
    user = principal.user
    if user.totp_enabled:
        raise AppError("2FA already enabled", code="totp_already_enabled")
    user.totp_secret = pyotp.random_base32()
    db.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="PhishGuard")
    return {"secret": user.totp_secret, "otpauth_uri": uri}


@router.post("/2fa/verify", response_model=Message)
def totp_verify(body: TotpVerifyIn, request: Request, principal: UserOnly, db: DB):
    user = principal.user
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise AppError("Invalid code", code="invalid_totp")
    user.totp_enabled = True
    audit_p(db, principal, request, "auth.2fa_enabled", "user", user.id)
    db.commit()
    return {"message": "Two-factor authentication enabled"}


@router.post("/2fa/disable", response_model=Message)
def totp_disable(body: TotpVerifyIn, request: Request, principal: UserOnly, db: DB):
    user = principal.user
    if not user.totp_enabled or not pyotp.TOTP(user.totp_secret or "").verify(body.code, valid_window=1):
        raise AppError("Invalid code", code="invalid_totp")
    user.totp_enabled, user.totp_secret = False, None
    audit_p(db, principal, request, "auth.2fa_disabled", "user", user.id)
    db.commit()
    return {"message": "Two-factor authentication disabled"}


# ---------------------------------------------------------------- invites (in-app, no email)

@router.post("/invite/accept", response_model=SessionOut, dependencies=[AuthLimit])
def accept_invite(body: InviteAccept, request: Request, response: Response, db: DB):
    invite = db.scalar(select(Invite).where(Invite.code_hash == sha256(body.code), Invite.deleted_at.is_(None)))
    if not invite or invite.used_at or invite.expires_at < utcnow():
        raise NotFound("Invite code is invalid or expired", code="invalid_invite")
    if db.scalar(select(User.id).where(User.email == invite.email)):
        raise AppError("An account with this email already exists", code="email_taken", status_code=409)
    user = User(org_id=invite.org_id, email=invite.email, full_name=body.full_name,
                password_hash=hash_password(body.password), role=invite.role)
    db.add(user)
    invite.used_at = utcnow()
    db.flush()
    audit(db, org_id=invite.org_id, action="user.invite_accepted", entity_type="user", entity_id=user.id,
          actor_id=user.id, actor_email=user.email, request=request)
    tokens = issue_session(db, response, user)
    db.commit()
    return session_payload(db, user, tokens, False)


# ---------------------------------------------------------------- OIDC (mock provider only)

@router.get("/oidc/providers")
def oidc_providers():
    s = get_settings()
    return {"providers": [{"name": "mock", "label": "Mock IdP (demo only)", "enabled": s.oidc_mock_enabled}]}


class MockAuthorizeIn(BaseModel):
    email: EmailStr


@router.post("/oidc/mock/authorize", dependencies=[AuthLimit])
def oidc_mock_authorize(body: MockAuthorizeIn):
    """Stands in for the IdP's consent screen: returns an authorization code for the email."""
    if not get_settings().oidc_mock_enabled:
        raise Forbidden("Mock OIDC provider is disabled")
    provider = PROVIDERS["mock"]
    assert isinstance(provider, MockOIDCProvider)
    return {"code": provider.issue_code(body.email)}


class OIDCCallbackIn(BaseModel):
    code: str


@router.post("/oidc/{provider}/callback", response_model=SessionOut, dependencies=[AuthLimit])
def oidc_callback(provider: str, body: OIDCCallbackIn, request: Request, response: Response, db: DB):
    if provider not in PROVIDERS or (provider == "mock" and not get_settings().oidc_mock_enabled):
        raise NotFound("Unknown identity provider")
    try:
        identity = PROVIDERS[provider].exchange_code(body.code, redirect_uri="")
    except ValueError:
        raise Unauthorized("Invalid authorization code")
    # Just-in-time linking: the IdP email must match an existing active user (no auto-provisioning).
    user = db.scalar(select(User).where(User.email == identity.email, User.deleted_at.is_(None)))
    if not user or not user.is_active:
        raise Unauthorized("No active account is linked to this identity")
    tokens = issue_session(db, response, user)
    audit(db, org_id=user.org_id, action="auth.login_oidc", entity_type="user", entity_id=user.id,
          actor_id=user.id, actor_email=user.email, request=request, details={"provider": provider})
    db.commit()
    return session_payload(db, user, tokens, False)


@router.patch("/me/preferences", response_model=UserOut)
def update_preferences(request: Request, db: DB, principal: UserOnly,
                       leaderboard_opt_in: Annotated[bool, Body(embed=True)]):
    principal.user.leaderboard_opt_in = leaderboard_opt_in
    audit_p(db, principal, request, "user.preferences_updated", "user", principal.id,
            leaderboard_opt_in=leaderboard_opt_in)
    db.commit()
    return principal.user


@router.get("/me/target")
def my_target(principal: UserOnly, db: DB):
    t = db.scalar(select(Target).where(Target.user_id == principal.id, Target.deleted_at.is_(None)))
    return {"target_id": t.id if t else None}


_ = get_principal  # re-exported for tests
