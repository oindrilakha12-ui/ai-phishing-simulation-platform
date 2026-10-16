"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import Counter, Histogram

from app.api.routes import admin, ai, analytics, auth, campaigns, health, people, reports, templates, training
from app.core.config import get_settings
from app.core.errors import envelope, install_error_handlers
from app.core.logging import configure_logging, get_logger, request_id_ctx

log = get_logger("app")
REQUESTS = Counter("phishguard_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("phishguard_http_request_seconds", "HTTP request latency", ["method", "route"])
API_PREFIX = "/api/v1"


async def _scheduler_loop() -> None:
    """Every 60s, activate scheduled campaigns that are due (synthetic delivery only)."""
    from app.api.routes.campaigns import activate_due_campaigns
    from app.db.session import SessionLocal

    while True:
        await asyncio.sleep(60)
        try:
            with SessionLocal() as db:
                n = await asyncio.to_thread(activate_due_campaigns, db, None)
                if n:
                    log.info("scheduler_activated", extra={"count": n})
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler_error", extra={"error": repr(exc)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    s.check_production_safety()
    task = asyncio.create_task(_scheduler_loop()) if s.environment != "test" else None
    log.info("startup", extra={"database": "sqlite" if s.is_sqlite else "postgresql", "demo_mode": s.demo_mode})
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="PhishGuard API",
        version="1.0.0",
        description="Defensive security-awareness training platform. No email is ever sent; all learners are "
                    "synthetic; all lures are fictional-brand, watermarked, preview-only.",
        lifespan=lifespan,
        docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def core_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:40] or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > s.max_request_bytes:
                return envelope(413, "payload_too_large", f"Request body exceeds {s.max_request_bytes} bytes")
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - start
        REQUESTS.labels(request.method, path, response.status_code).inc()
        LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = rid
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if s.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        if path != "/metrics" and not path.startswith("/health"):
            log.info("request", extra={"method": request.method, "path": path, "status": response.status_code,
                                       "duration_ms": round(elapsed * 1000, 1)})
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(CORSMiddleware, allow_origins=[s.frontend_origin], allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "Authorization", "X-API-Key", "X-Request-ID"])

    for r in (auth.router, people.router, templates.router, campaigns.router, analytics.router, training.router,
              reports.router, ai.router, admin.router):
        app.include_router(r, prefix=API_PREFIX)
    app.include_router(health.router)
    return app


app = create_app()
