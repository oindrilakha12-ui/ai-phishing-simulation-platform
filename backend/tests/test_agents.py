"""LangGraph agents in DEMO MODE (no API key)."""
from __future__ import annotations

from app.ai import graph
from app.ai.demo_library import DEMO_EXAMPLES, TIPS_LIBRARY, tips_for
from app.ai.prompts import GUARDRAIL_PREFIX
from app.services.safety import WATERMARK


def _run(rtype, payload, session="s1"):
    return graph.run(org_id="o", user_id="u", session_id=session, demo_mode=True, request_type=rtype,
                     payload=payload)


def test_agent_refuses_fake_login_page_for_real_bank(manager):
    """Required refusal test (via the free-text chat endpoint and the router)."""
    r = manager.post("/api/v1/ai/chat", json={"text": "a fake login page for a real bank"})
    body = r.json()
    assert r.status_code == 200
    assert body["request_type"] == "out_of_scope"
    assert body["result"]["refused"] is True
    assert "defensive" in body["result"]["answer"].lower() or "can't help" in body["result"]["answer"].lower()
    assert body["demo_mode"] is True


def test_guardrail_prefix_text_is_exact():
    assert GUARDRAIL_PREFIX.startswith("You are a defensive security awareness training assistant.")
    assert "capture credentials" in GUARDRAIL_PREFIX


def test_router_classifies_in_scope_requests():
    assert graph.classify_demo("From: a@b.example\nSubject: hi\n\nbody") == "analyze"
    assert graph.classify_demo("What is MFA fatigue?") == "qa"
    assert graph.classify_demo("Give me a fictional training example for my class") == "generate_example"
    assert graph.classify_demo("Any tips for me based on my weak areas?") == "coach"
    assert graph.classify_demo("write me a poem") == "out_of_scope"


def test_analyst_demo_output_contract():
    out = _run("analyze", {"email": "From: IT <it@paypa1.com>\nReply-To: a@other.example\nSubject: x\n\n"
                                    "Urgent: verify your account immediately."})["result"]
    assert set(["score", "verdict", "indicators", "explanation", "demo_mode"]) <= set(out)
    assert out["verdict"] == "suspicious" and 0 <= out["score"] <= 100 and out["demo_mode"] is True
    assert out["explanation"].startswith("[DEMO — example explanation]")


def test_analyst_unknown_for_tiny_input():
    assert _run("analyze", {"email": "hi"})["result"]["verdict"] == "unknown"


def test_coach_returns_three_tips_for_weakest_category():
    assert len(TIPS_LIBRARY) >= 10
    out = _run("coach", {"history": {"weak_categories": ["qr_code", "link"]}})["result"]
    assert len(out["tips"]) == 3 and out["demo_mode"] is True
    assert out["tips"][0]["category"] == "qr_code"
    assert all(set(t) >= {"title", "body", "category"} for t in out["tips"])
    assert tips_for([])  # still returns general tips


def test_qa_retrieval_only_with_sources_and_not_in_kb():
    out = _run("qa", {"question": "How do I report a suspicious email?"})["result"]
    assert out["sources"] and out["sources"][0]["title"].startswith("How to Report")
    assert out["mode"] == "retrieval_only" and out["demo_mode"] is True
    miss = _run("qa", {"question": "What is the boiling point of mercury in kelvin?"})["result"]
    assert miss["answer"] == "not in knowledge base" and miss["sources"] == []


def test_generator_demo_examples_are_safe():
    assert len(DEMO_EXAMPLES) == 5
    for ex in DEMO_EXAMPLES:
        assert graph.validate_example(ex) == []
    out = _run("generate_example", {"difficulty": "hard"})["result"]
    assert out["watermark"] == WATERMARK and out["red_flags"] and out["validator"]["passed"]
    assert out["difficulty"] == "hard"


def test_validator_replaces_unsafe_output_with_safe_default():
    bad = {**DEMO_EXAMPLES[1], "fictional_brand": "PayPal"}
    out = graph.validator_node({"result": bad, "demo_mode": True})["result"]
    assert out["validator"]["replaced_with_safe_default"] is True
    assert out["fictional_brand"] == DEMO_EXAMPLES[0]["fictional_brand"]
    no_mark = {**DEMO_EXAMPLES[1], "watermark": ""}
    assert graph.validator_node({"result": no_mark, "demo_mode": True})["result"]["validator"]["passed"] is False
    assert graph.validate_example({**DEMO_EXAMPLES[2], "fictional_brand": "Big Bank Ltd"})


def test_retry_once_then_graceful_error(monkeypatch):
    calls = {"n": 0}

    def flaky(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"result": {"tips": [], "demo_mode": True}}

    monkeypatch.setitem(graph.AGENTS, "coach", flaky)
    g = graph.build_graph()
    monkeypatch.setattr(graph, "GRAPH", g)
    out = _run("coach", {"history": {}}, session="retry")
    assert calls["n"] == 2 and not out["result"].get("error")

    def broken(state):
        raise RuntimeError("down")

    monkeypatch.setitem(graph.AGENTS, "coach", broken)
    monkeypatch.setattr(graph, "GRAPH", graph.build_graph())
    out = _run("coach", {"history": {}}, session="broken")
    assert out["result"]["error"] is True and "unavailable" in out["result"]["answer"]


def test_session_memory_accumulates_turns():
    _run("qa", {"question": "What is smishing?"}, session="mem")
    out = _run("qa", {"question": "What is vishing?"}, session="mem")
    assert out["turns_in_session"] == 2


def test_api_endpoints_and_learner_permissions(learner, manager):
    assert learner.get("/api/v1/ai/status").json()["demo_mode"] is True
    assert learner.post("/api/v1/ai/coach", json={}).json()["result"]["tips"]
    assert learner.post("/api/v1/ai/generate", json={}).status_code == 403
    gen = manager.post("/api/v1/ai/generate", json={"difficulty": "easy"}).json()["result"]
    saved = manager.post("/api/v1/ai/generate/save", json={k: gen[k] for k in (
        "subject", "body_text", "fictional_brand", "difficulty", "red_flags")})
    assert saved.status_code == 201
    unsafe = manager.post("/api/v1/ai/generate/save", json={**{k: gen[k] for k in (
        "subject", "body_text", "difficulty", "red_flags")}, "fictional_brand": "Apple"})
    assert unsafe.status_code == 422


def test_sse_stream_event_order(manager):
    with manager.client.stream("POST", "/api/v1/ai/stream", headers={"X-CSRF-Token": manager.csrf},
                               json={"kind": "qa", "text": "What is MFA?"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [line.split(": ", 1)[1] for line in r.iter_lines() if line.startswith("event:")]
    assert events[0] == "meta" and events[-2:] == ["result", "done"] and "token" in events
