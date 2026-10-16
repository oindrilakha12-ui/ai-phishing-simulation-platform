"""AI Studio endpoints. Every response carries demo_mode so the UI can show the DEMO badge."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.ai import graph, rag
from app.api.deps import DB, Learner, Manager, repo_for
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.ratelimit import rate_limit
from app.db.models import Enrollment, SimulationEvent, Target, Template
from app.services.audit import audit_p
from app.services.safety import ensure_watermark, validate_lure

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(rate_limit("ai", "rate_limit_ai"))])


@router.get("/status")
def ai_status(_: Learner):
    s = get_settings()
    return {"demo_mode": s.demo_mode, "provider": "demo" if s.demo_mode else s.ai_provider,
            "vector_store": rag.get_store().backend,
            "embedding": "local hashing embedder (lexical, offline)",
            "label": "DEMO MODE — deterministic outputs, no LLM" if s.demo_mode else "LIVE"}


def learner_history(db, org_id: str, target_id: str) -> dict:
    """Synthetic training history used by the Awareness Coach."""
    clicks = db.scalars(select(SimulationEvent.red_flag_category).where(
        SimulationEvent.org_id == org_id, SimulationEvent.target_id == target_id,
        SimulationEvent.event_type == "clicked_sim")).all()
    reports = db.scalar(select(SimulationEvent.id).where(
        SimulationEvent.target_id == target_id, SimulationEvent.event_type == "reported").limit(1))
    enrolls = db.scalars(select(Enrollment.status).where(Enrollment.org_id == org_id,
                                                         Enrollment.target_id == target_id,
                                                         Enrollment.deleted_at.is_(None))).all()
    counts = Counter(c for c in clicks if c)
    weak = [c for c, _ in counts.most_common()]
    if not reports:
        weak.append("reporting")
    return {"failed_categories": dict(counts), "weak_categories": weak or ["reporting"],
            "completion_rate": round(sum(1 for s in enrolls if s == "completed") / len(enrolls), 2) if enrolls else None,
            "simulated_clicks": len(clicks), "has_reported": bool(reports), "synthetic": True}


class AnalyzeIn(BaseModel):
    email: str = Field(min_length=1, max_length=50_000)
    session_id: str | None = Field(default=None, max_length=64)


class CoachIn(BaseModel):
    target_id: str | None = Field(default=None, max_length=32, description="Managers may coach a specific person")
    session_id: str | None = Field(default=None, max_length=64)


class QAIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    session_id: str | None = Field(default=None, max_length=64)


class GenerateIn(BaseModel):
    difficulty: Literal["easy", "medium", "hard"] | None = None
    topic: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=64)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=64)


class StreamIn(BaseModel):
    kind: Literal["analyze", "coach", "qa", "generate_example", "chat"]
    text: str = Field(default="", max_length=50_000)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    target_id: str | None = Field(default=None, max_length=32)
    session_id: str | None = Field(default=None, max_length=64)


def _run(principal, request_type, payload, session_id):
    return graph.run(org_id=principal.org_id, user_id=principal.id, session_id=session_id or uuid.uuid4().hex,
                     demo_mode=get_settings().demo_mode, request_type=request_type, payload=payload)


def _coach_payload(db, principal, target_id: str | None) -> dict:
    if target_id:
        if principal.role == "learner":
            raise AppError("Learners can only coach themselves", code="forbidden", status_code=403)
        t = repo_for(principal, db).get(Target, target_id)
    else:
        t = db.scalar(select(Target).where(Target.user_id == principal.id, Target.deleted_at.is_(None)))
        if not t:
            raise NotFound("No learner profile linked to this account; pass target_id")
    return {"history": learner_history(db, principal.org_id, t.id), "target_name": t.full_name}


@router.post("/analyze")
def analyze(body: AnalyzeIn, request: Request, principal: Learner, db: DB):
    out = _run(principal, "analyze", {"email": body.email}, body.session_id)
    audit_p(db, principal, request, "ai.analyze", "ai", None, score=out["result"].get("score"))
    db.commit()
    return out


@router.post("/coach")
def coach(body: CoachIn, request: Request, principal: Learner, db: DB):
    out = _run(principal, "coach", _coach_payload(db, principal, body.target_id), body.session_id)
    audit_p(db, principal, request, "ai.coach", "ai", body.target_id)
    db.commit()
    return out


@router.post("/qa")
def qa(body: QAIn, request: Request, principal: Learner, db: DB):
    out = _run(principal, "qa", {"question": body.question}, body.session_id)
    audit_p(db, principal, request, "ai.qa", "ai", None)
    db.commit()
    return out


@router.post("/generate")
def generate(body: GenerateIn, request: Request, principal: Manager, db: DB):
    out = _run(principal, "generate_example", {"difficulty": body.difficulty, "topic": body.topic}, body.session_id)
    audit_p(db, principal, request, "ai.generate_example", "ai", None,
            validator_passed=out["result"].get("validator", {}).get("passed"))
    db.commit()
    return out


@router.post("/chat")
def chat(body: ChatIn, request: Request, principal: Learner, db: DB):
    """Free-text entry point: the router node decides which agent handles it (or refuses)."""
    out = _run(principal, None, {"text": body.text}, body.session_id)
    audit_p(db, principal, request, "ai.chat", "ai", None, routed_to=out["request_type"])
    db.commit()
    return out


class SaveExampleIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body_text: str = Field(min_length=10, max_length=10_000)
    fictional_brand: str = Field(max_length=60)
    difficulty: Literal["easy", "medium", "hard"]
    red_flags: list[dict] = Field(min_length=1, max_length=20)


@router.post("/generate/save", status_code=201)
def save_example(body: SaveExampleIn, request: Request, principal: Manager, db: DB):
    """Turn a validated training example into a campaign template (re-validated server-side)."""
    import html

    slug = body.fictional_brand.lower().replace(" ", "")
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in body.body_text.split("\n") if p.strip())
    data = {
        "name": f"{body.fictional_brand}: {body.subject}"[:120], "brand": body.fictional_brand,
        "category": body.red_flags[0].get("category", "link"), "difficulty": body.difficulty,
        "subject": body.subject, "sender_name": f"{body.fictional_brand} Team",
        "sender_email": f"notifications@{slug}-notice.example",
        "body_html": ensure_watermark(paragraphs),
        "red_flags": [{"id": f"f{i + 1}", "category": f.get("category", "link"),
                       "description": str(f.get("description", ""))[:400], "cue": str(f.get("cue", ""))[:200]}
                      for i, f in enumerate(body.red_flags)],
    }
    problems = validate_lure(data)
    if problems:
        raise AppError("Example violates the safety scope", code="unsafe_template", status_code=422,
                       details=problems)
    source = "ai_demo" if get_settings().demo_mode else "ai"
    t = repo_for(principal, db).add(Template, **data, version=1, source=source)
    audit_p(db, principal, request, "template.created_from_ai", "template", t.id, source=source)
    db.commit()
    return {"template_id": t.id, "name": t.name}


# ------------------------------------------------------------------ SSE streaming

def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream_text(result: dict) -> str:
    if result.get("refused") or result.get("error"):
        return result.get("answer", "")
    for key in ("explanation", "answer"):
        if result.get(key):
            return result[key]
    if result.get("tips"):
        return "\n\n".join(f"{t['title']}: {t['body']}" for t in result["tips"])
    if result.get("subject"):
        return f"Subject: {result['subject']}\n\n{result.get('body_text', '')}"
    return ""


@router.post("/stream")
async def stream(body: StreamIn, request: Request, principal: Learner, db: DB):
    """Server-Sent Events: meta -> token* -> result -> done. Runs the graph, then streams the final
    output word by word (live providers could stream tokens directly; see docs)."""
    if body.kind == "generate_example" and principal.role == "learner":
        raise AppError("Requires role manager or higher", code="forbidden", status_code=403)
    if body.kind == "coach":
        payload = await run_in_threadpool(_coach_payload, db, principal, body.target_id)
    else:
        payload = {"analyze": {"email": body.text}, "qa": {"question": body.text},
                   "generate_example": {"difficulty": body.difficulty}, "chat": {"text": body.text}}[body.kind]
    rtype = None if body.kind == "chat" else body.kind
    session_id = body.session_id or uuid.uuid4().hex
    out = await run_in_threadpool(_run, principal, rtype, payload, session_id)
    audit_p(db, principal, request, f"ai.stream.{body.kind}", "ai", None, routed_to=out["request_type"])
    db.commit()

    async def gen():
        yield _sse("meta", {"request_type": out["request_type"], "demo_mode": out["demo_mode"],
                            "session_id": session_id})
        words = _stream_text(out["result"]).split(" ")
        for i in range(0, len(words), 3):
            if await request.is_disconnected():
                return
            yield _sse("token", {"text": " ".join(words[i:i + 3]) + " "})
            await asyncio.sleep(0.015)
        yield _sse("result", out)
        yield _sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
