from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready():
    """Ready when the database answers. Reports which DB backend and AI mode are active."""
    s = get_settings()
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    body = {"status": "ok" if db_ok else "degraded", "database": "sqlite" if s.is_sqlite else "postgresql",
            "database_ok": db_ok, "demo_mode": s.demo_mode}
    return JSONResponse(body, status_code=200 if db_ok else 503)


@router.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
