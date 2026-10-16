"""SSO-readiness: a small OIDC provider abstraction.

Only `MockOIDCProvider` is implemented (for demos and tests). A real IdP (Entra ID, Okta,
Google Workspace) would implement the same interface using the authorization-code + PKCE
flow; see docs/ARCHITECTURE.md#sso. Real IdP integration is NOT claimed as working.
"""
from __future__ import annotations

import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OIDCIdentity:
    subject: str
    email: str
    name: str
    issuer: str


class OIDCProvider(ABC):
    name: str

    @abstractmethod
    def authorization_url(self, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> OIDCIdentity: ...


class MockOIDCProvider(OIDCProvider):
    """Pretends to be an IdP. The 'authorize' step lets you pick a seeded user's email; the
    code it returns maps back to that email. Clearly for demos only."""

    name = "mock"
    _codes: dict[str, tuple[str, float]] = {}

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        return f"/sso/mock?state={state}&redirect_uri={redirect_uri}"

    def issue_code(self, email: str) -> str:
        code = secrets.token_urlsafe(16)
        self._codes[code] = (email.lower(), time.time() + 120)
        return code

    def exchange_code(self, code: str, redirect_uri: str) -> OIDCIdentity:
        email, exp = self._codes.pop(code, ("", 0.0))
        if not email or exp < time.time():
            raise ValueError("invalid or expired code")
        return OIDCIdentity(subject=f"mock|{email}", email=email, name=email.split("@")[0], issuer="mock-idp")


PROVIDERS: dict[str, OIDCProvider] = {"mock": MockOIDCProvider()}
