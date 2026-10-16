"""LangGraph multi-agent graph.

    START -> router --(analyze)----------> analyst ----\
                    --(coach)------------> coach ------+--> [error? -> retry (once) -> same agent | error_node]
                    --(qa)---------------> qa ---------+
                    --(generate_example)-> generator --+--> validator -> END
                    --(out_of_scope)-----> refuse -> END

Shared state: org_id, user_id, session_id, messages[], demo_mode (+ working fields).
Guardrail: every live LLM call is prefixed with GUARDRAIL_PREFIX (see providers.py). In DEMO MODE
the router only accepts the four in-scope request types, and anything else is refused.
Session memory: a LangGraph MemorySaver checkpointer keyed by session_id.
"""
from __future__ import annotations

import operator
import random
import re
import time
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.ai import heuristics, rag
from app.ai.demo_library import DEMO_EXAMPLES, tips_for
from app.ai.prompts import (
    ANALYST_PROMPT,
    COACH_PROMPT,
    DEFENSIVE_ALTERNATIVE,
    GENERATOR_PROMPT,
    QA_PROMPT,
    ROUTER_PROMPT,
)
from app.ai.providers import get_provider, parse_json
from app.core.logging import get_logger
from app.services.safety import WATERMARK, is_fictional_brand

log = get_logger(__name__)

RequestType = Literal["analyze", "coach", "qa", "generate_example", "out_of_scope"]
# The real-brand check the validator applies to generated examples (as specified).
KNOWN_REAL_BRANDS = ["gmail", "paypal", "amazon", "apple", "microsoft", "facebook", "bank"]
DEMO_EXPLANATION_LABEL = "DEMO — example explanation"
NOT_IN_KB = "not in knowledge base"


class AgentState(TypedDict, total=False):
    org_id: str
    user_id: str | None
    session_id: str
    messages: Annotated[list[dict[str, Any]], operator.add]  # appended across turns (session memory)
    demo_mode: bool
    # working fields for one turn
    request_type: RequestType | None
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    attempts: int
    usage: dict[str, Any]


# ------------------------------------------------------------------ router

QUESTION_START = re.compile(r"^(what|how|why|when|where|who|which|is|are|can|could|should|do|does|explain|"
                            r"tell me|define)\b", re.I)


def classify_demo(text: str) -> RequestType:
    """Deterministic in-scope classifier for DEMO MODE. Only the four supported request types are
    accepted; everything else is out_of_scope (and therefore refused)."""
    t = text.strip()
    low = t.lower()
    if re.search(r"^(from|subject|to|reply-to|received|return-path|authentication-results):", t, re.I | re.M) or \
            low.startswith(("analyze", "analyse", "check this email", "is this email")):
        return "analyze"
    if re.search(r"\b(training example|example (phishing )?email for (a |my )?(class|training)|"
                 r"fictional (training )?example)\b", low):
        return "generate_example"
    if re.search(r"\b(coach|tips? for me|my (weak|training)|how am i doing)\b", low):
        return "coach"
    if t.endswith("?") or QUESTION_START.match(t):
        return "qa"
    return "out_of_scope"


def router_node(state: AgentState) -> dict:
    if state.get("request_type"):  # explicit tab endpoints pass the type directly
        return {}
    text = state["input"].get("text", "")
    provider = get_provider()
    if provider is None:
        rtype = classify_demo(text)
    else:
        try:
            reply = provider.complete(ROUTER_PROMPT, text[:4000], max_tokens=5).text.strip().lower()
            rtype = reply if reply in ("analyze", "coach", "qa", "generate_example") else "out_of_scope"
        except Exception as exc:  # noqa: BLE001 - fall back to the deterministic router
            log.warning("router_llm_failed", extra={"error": repr(exc)})
            rtype = classify_demo(text)
    return {"request_type": rtype}


def route_after_router(state: AgentState) -> str:
    return {"analyze": "analyst", "coach": "coach", "qa": "qa", "generate_example": "generator"}.get(
        state.get("request_type") or "out_of_scope", "refuse")


# ------------------------------------------------------------------ agent nodes

def _usage(res) -> dict:
    return {"input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
            "llm_latency_ms": round(res.latency_ms, 1), "model": res.model}


def analyst_node(state: AgentState) -> dict:
    text = state["input"].get("email") or state["input"].get("text", "")
    if len(text.strip()) < 20:
        return {"result": {"score": 0, "verdict": "unknown", "indicators": [], "links": [],
                           "explanation": "Not enough text to analyze. Paste the full email, ideally with headers.",
                           "demo_mode": state["demo_mode"]}}
    h = heuristics.analyze(text)
    verdict = "suspicious" if h["score"] >= 20 else "safe"
    result = {"score": h["score"], "verdict": verdict, "heuristic_verdict": h["verdict"],
              "indicators": h["indicators"], "links": h["links"], "auth_results": h["auth_results"],
              "sender": h["sender"], "demo_mode": state["demo_mode"]}
    provider = get_provider()
    if provider is None:
        names = ", ".join(i["title"].lower() for i in h["indicators"][:4]) or "no strong warning signs"
        result["explanation"] = (
            f"[{DEMO_EXPLANATION_LABEL}] The rule-based checks found: {names}. Each indicator above "
            "explains why it matters. When several appear together, treat the email as suspicious: don't "
            "click or reply — report it with the Report Phish button.")
        return {"result": result}
    summary = "\n".join(f"- {i['id']}: {i['title']} ({i['severity']}) evidence: {i['evidence']}"
                        for i in h["indicators"]) or "- none"
    res = provider.complete(ANALYST_PROMPT, f"Indicators:\n{summary}\n\n<email>\n{text[:6000]}\n</email>")
    data = parse_json(res.text)
    notes = data.get("indicator_notes", {})
    for ind in result["indicators"]:
        ind["llm_note"] = notes.get(ind["id"])
    result["explanation"] = str(data.get("explanation", ""))[:3000]
    return {"result": result, "usage": _usage(res)}


def coach_node(state: AgentState) -> dict:
    history = state["input"].get("history", {})
    weak = history.get("weak_categories", [])
    provider = get_provider()
    if provider is None:
        tips = tips_for(weak)
        for t in tips:
            t["title"] = f"{t['title']}"
        return {"result": {"tips": tips, "demo_mode": True, "based_on": history}}
    res = provider.complete(COACH_PROMPT, f"Synthetic learner history: {history}")
    data = parse_json(res.text)
    tips = [{"title": str(t.get("title", ""))[:80], "body": str(t.get("body", ""))[:400],
             "category": str(t.get("category", "general"))[:40]} for t in data.get("tips", [])][:3]
    if len(tips) < 3:
        raise ValueError("coach returned fewer than 3 tips")
    return {"result": {"tips": tips, "demo_mode": False, "based_on": history}, "usage": _usage(res)}


def qa_node(state: AgentState) -> dict:
    question = state["input"].get("question") or state["input"].get("text", "")
    hits = rag.retrieve(question, k=3)
    confident = [h for h in hits if h["similarity"] >= rag.MIN_SIMILARITY]
    sources = [{"title": h["title"], "slug": h["slug"], "chunk_preview": h["text"][:220],
                "similarity": h["similarity"]} for h in confident]
    if not confident:
        return {"result": {"answer": NOT_IN_KB, "sources": [], "demo_mode": state["demo_mode"],
                           "mode": "retrieval_only" if state["demo_mode"] else "rag"}}
    provider = get_provider()
    if provider is None:  # retrieval-only mode: top chunk is the answer
        top = confident[0]
        return {"result": {"answer": top["text"], "sources": sources[:1], "demo_mode": True,
                           "mode": "retrieval_only"}}
    docs = "\n".join(f'<document title="{h["title"]}">\n{h["text"]}\n</document>' for h in confident)
    history = [m for m in state.get("messages", []) if m.get("role") in ("user", "assistant")][-4:]
    convo = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in history)
    res = provider.complete(QA_PROMPT, f"{docs}\n\nRecent conversation:\n{convo}\n\nQuestion: {question}")
    answer = res.text.strip()
    if NOT_IN_KB in answer.lower():
        return {"result": {"answer": NOT_IN_KB, "sources": [], "demo_mode": False, "mode": "rag"},
                "usage": _usage(res)}
    return {"result": {"answer": answer[:4000], "sources": sources, "demo_mode": False, "mode": "rag"},
            "usage": _usage(res)}


def generator_node(state: AgentState) -> dict:
    difficulty = state["input"].get("difficulty")
    provider = get_provider()
    if provider is None:
        pool = [e for e in DEMO_EXAMPLES if not difficulty or e["difficulty"] == difficulty] or DEMO_EXAMPLES
        idx = random.Random(state.get("session_id", "") + str(len(state.get("messages", [])))).randrange(len(pool))
        return {"result": {**dict(pool[idx]), "demo_mode": True, "label": "DEMO"}}
    topic = str(state["input"].get("topic", ""))[:200]
    res = provider.complete(GENERATOR_PROMPT,
                            f"Difficulty: {difficulty or 'medium'}. Training theme: {topic or 'workplace'}.")
    data = parse_json(res.text)
    return {"result": {**data, "demo_mode": False}, "usage": _usage(res)}


def validate_example(ex: dict) -> list[str]:
    """Post-generation checks for a training example. Empty list == valid."""
    problems = []
    if ex.get("watermark") != WATERMARK:
        problems.append("watermark missing")
    brand = str(ex.get("fictional_brand", "")).lower()
    if not brand or any(b in brand for b in KNOWN_REAL_BRANDS) or not is_fictional_brand(brand):
        problems.append("fictional_brand is not an approved fictional brand")
    if not isinstance(ex.get("red_flags"), list) or not ex["red_flags"]:
        problems.append("red_flags missing")
    if not ex.get("subject") or not ex.get("body_text"):
        problems.append("subject/body missing")
    return problems


def validator_node(state: AgentState) -> dict:
    ex = dict(state.get("result") or {})
    problems = validate_example(ex)
    if problems:
        log.warning("generator_output_rejected", extra={"problems": problems})
        safe = {**DEMO_EXAMPLES[0], "demo_mode": state["demo_mode"], "label": "SAFE DEFAULT",
                "validator": {"passed": False, "problems": problems, "replaced_with_safe_default": True}}
        return {"result": safe}
    ex["validator"] = {"passed": True, "problems": []}
    return {"result": ex}


def refuse_node(state: AgentState) -> dict:
    return {"result": {"refused": True, "answer": DEFENSIVE_ALTERNATIVE, "demo_mode": state["demo_mode"]}}


# ------------------------------------------------------------------ error handling

AGENTS = {"analyst": analyst_node, "coach": coach_node, "qa": qa_node, "generator": generator_node}


def guarded(name: str):
    """Wrap an agent so exceptions become state (the graph decides to retry or fail gracefully)."""
    fn = AGENTS[name]

    def _node(state: AgentState) -> dict:
        try:
            out = fn(state)
            return {**out, "error": None}
        except Exception as exc:  # noqa: BLE001
            log.warning("agent_failed", extra={"agent": name, "error": repr(exc)})
            return {"error": f"{name}: {type(exc).__name__}", "attempts": state.get("attempts", 0) + 1}

    return _node


def after_agent(name: str):
    def _route(state: AgentState) -> str:
        if state.get("error"):
            return name if state.get("attempts", 0) < 2 else "error_node"  # retry once
        return "validator" if name == "generator" else "finish"
    return _route


def error_node(state: AgentState) -> dict:
    return {"result": {"error": True, "answer": "The assistant is temporarily unavailable. Please try again. "
                                                "Rule-based tools (analyzer, knowledge search) still work.",
                       "demo_mode": state["demo_mode"]}}


def finish_node(state: AgentState) -> dict:
    """Append this turn to session memory."""
    summary = (state.get("result") or {}).get("answer") or (state.get("result") or {}).get("explanation") or \
        (state.get("result") or {}).get("subject") or ""
    return {"messages": [
        {"role": "user", "content": str(state["input"].get("text") or state["input"].get("question") or
                                        state.get("request_type"))[:500]},
        {"role": "assistant", "content": str(summary)[:500], "request_type": state.get("request_type")},
    ]}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", router_node)
    for name in AGENTS:
        g.add_node(name, guarded(name))
    g.add_node("validator", validator_node)
    g.add_node("refuse", refuse_node)
    g.add_node("error_node", error_node)
    g.add_node("finish", finish_node)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_after_router,
                            {"analyst": "analyst", "coach": "coach", "qa": "qa", "generator": "generator",
                             "refuse": "refuse"})
    for name in AGENTS:
        targets = {name: name, "error_node": "error_node", "finish": "finish"}
        if name == "generator":
            targets["validator"] = "validator"
        g.add_conditional_edges(name, after_agent(name), targets)
    g.add_edge("validator", "finish")
    g.add_edge("refuse", "finish")
    g.add_edge("error_node", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = build_graph()


def run(*, org_id: str, user_id: str | None, session_id: str, demo_mode: bool,
        request_type: RequestType | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one turn through the graph and return the result plus metadata."""
    start = time.perf_counter()
    # Thread id includes org + user so sessions can never be shared across tenants/users.
    thread = f"{org_id}:{user_id}:{session_id}"
    state = GRAPH.invoke({"org_id": org_id, "user_id": user_id, "session_id": session_id, "demo_mode": demo_mode,
                          "request_type": request_type, "input": payload, "result": None, "error": None,
                          "attempts": 0, "usage": {}},
                         config={"configurable": {"thread_id": thread}})
    return {"request_type": state.get("request_type") or "out_of_scope", "result": state.get("result") or {},
            "demo_mode": demo_mode, "usage": state.get("usage") or {},
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "turns_in_session": len(state.get("messages", [])) // 2}
