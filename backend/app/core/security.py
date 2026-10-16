"""Password hashing, password policy, JWT creation/validation and API-key hashing."""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

# ---------------------------------------------------------------- passwords

PASSWORD_RULES = [
    (r".{12,}", "at least 12 characters"),
    (r"[A-Z]", "an uppercase letter"),
    (r"[a-z]", "a lowercase letter"),
    (r"\d", "a digit"),
    (r"[^A-Za-z0-9]", "a symbol"),
]


def password_policy_errors(password: str) -> list[str]:
    """Return the list of unmet rules (empty list == password is acceptable)."""
    missing = [label for pattern, label in PASSWORD_RULES if not re.search(pattern, password)]
    if len(password.encode()) > 72:  # bcrypt only uses the first 72 bytes
        missing.append("at most 72 bytes")
    return missing


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except ValueError:
        return False


# A real hash of a random string: used to keep login timing similar for unknown users.
DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12)).decode()

# ---------------------------------------------------------------- JWT


def _now() -> datetime:
    return datetime.now(UTC)


def create_token(*, subject: str, org_id: str, role: str, token_type: str,
                 family: str | None = None) -> tuple[str, str, datetime]:
    """Create a signed JWT. Returns (token, jti, expires_at)."""
    s = get_settings()
    jti = uuid.uuid4().hex
    lifetime = (timedelta(minutes=s.access_token_minutes) if token_type == "access"
                else timedelta(days=s.refresh_token_days))
    exp = _now() + lifetime
    claims: dict[str, Any] = {
        "sub": subject, "org": org_id, "role": role, "type": token_type,
        "jti": jti, "iat": _now(), "exp": exp,
    }
    if family:
        claims["fam"] = family  # refresh-token family, used for reuse detection
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm), jti, exp


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm],
                        options={"require": ["exp", "sub", "jti", "type"]})
    if claims.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return claims


# ---------------------------------------------------------------- API keys / misc


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, prefix, sha256_hash). Only the hash is stored."""
    raw = "pg_" + secrets.token_urlsafe(32)
    return raw, raw[:10], sha256(raw)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
