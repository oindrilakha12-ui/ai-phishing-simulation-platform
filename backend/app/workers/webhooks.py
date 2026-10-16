"""Outbound webhooks: HMAC-signed JSON POSTs to *registered* URLs only, with retry/backoff.

This is the only outbound network call the platform makes. It never sends email.
Runs via FastAPI BackgroundTasks (in-process). With Redis enabled you would move this to a
real queue worker (see docs/PRODUCTION_ROADMAP.md).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Webhook, WebhookDelivery
from app.db.session import SessionLocal

log = get_logger(__name__)
MAX_ATTEMPTS = 3
SIGNATURE_HEADER = "X-PhishGuard-Signature"


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def validate_webhook_url(url: str) -> str | None:
    """Return an error string if the URL is not acceptable (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return "URL must be http(s) with a host"
    if get_settings().environment == "production":
        if parsed.scheme != "https":
            return "URL must use https in production"
        try:
            for info in socket.getaddrinfo(parsed.hostname, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return "URL resolves to a private/internal address"
        except socket.gaierror:
            return "URL host does not resolve"
    return None


def enqueue(db: Session, org_id: str, event: str, payload: dict[str, Any]) -> list[str]:
    """Create pending deliveries for every active webhook subscribed to `event`."""
    hooks = db.scalars(select(Webhook).where(Webhook.org_id == org_id, Webhook.is_active.is_(True),
                                             Webhook.deleted_at.is_(None))).all()
    ids = []
    for h in hooks:
        if h.events and event not in h.events and "*" not in h.events:
            continue
        d = WebhookDelivery(org_id=org_id, webhook_id=h.id, event=event, payload=payload)
        db.add(d)
        db.flush()
        ids.append(d.id)
    return ids


def deliver(delivery_ids: list[str], sleep=time.sleep, client: httpx.Client | None = None) -> None:
    """Attempt each delivery up to MAX_ATTEMPTS times with exponential backoff (1s, 2s)."""
    db = SessionLocal()
    http = client or httpx.Client(timeout=5.0, follow_redirects=False)
    try:
        for did in delivery_ids:
            d = db.get(WebhookDelivery, did)
            hook = db.get(Webhook, d.webhook_id) if d else None
            if not d or not hook:
                continue
            body = json.dumps({"event": d.event, "delivery_id": d.id, "data": d.payload}, default=str).encode()
            while d.attempts < MAX_ATTEMPTS and d.status != "success":
                d.attempts += 1
                ts = str(int(time.time()))
                try:
                    r = http.post(hook.url, content=body, headers={
                        "Content-Type": "application/json", SIGNATURE_HEADER: sign(hook.secret, ts, body),
                        "User-Agent": "PhishGuard-Webhooks/1.0"})
                    d.response_code = r.status_code
                    if 200 <= r.status_code < 300:
                        d.status, d.last_error = "success", None
                    else:
                        d.last_error = f"HTTP {r.status_code}"
                except httpx.HTTPError as exc:
                    d.last_error = type(exc).__name__ + ": " + str(exc)[:200]
                db.commit()
                if d.status != "success" and d.attempts < MAX_ATTEMPTS:
                    sleep(2 ** (d.attempts - 1))
            if d.status != "success":
                d.status = "failed"
                db.commit()
                log.warning("webhook_failed", extra={"delivery_id": d.id, "error": d.last_error})
    finally:
        if client is None:
            http.close()
        db.close()
