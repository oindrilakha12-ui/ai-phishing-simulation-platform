from __future__ import annotations

from app.ai import heuristics as h


def ids(result):
    return {i["id"] for i in result["indicators"]}


def test_levenshtein():
    assert h.levenshtein("kitten", "sitting") == 3
    assert h.levenshtein("same", "same") == 0


def test_lookalike_and_homoglyph_detection():
    assert h.lookalike_of("paypa1.com") == "paypal.com"
    assert h.lookalike_of("rnicrosoft.com") == "microsoft.com"
    assert h.lookalike_of("micros0ft-support.example") == "microsoft.com"
    assert h.lookalike_of("xn--pple-43d.com") is not None
    assert h.lookalike_of("paypal.com") is None
    assert h.lookalike_of("university.example") is None


def test_auth_results_parsing():
    r = h.parse_auth_results("mx.example; spf=fail smtp.mailfrom=x; dkim=pass; dmarc=fail")
    assert r == {"spf": "fail", "dkim": "pass", "dmarc": "fail"}


def test_header_based_indicators():
    raw = ("Authentication-Results: mx.example; spf=softfail; dkim=none; dmarc=fail\n"
           "From: \"accounts@globex.example\" <billing@globex-pay.example>\n"
           "Reply-To: refunds@elsewhere.example\nSubject: Invoice\n\nHello")
    res = h.analyze(raw)
    assert {"auth_spf", "auth_dmarc", "reply_to_mismatch", "display_name_spoof", "lookalike_sender"} <= ids(res)


def test_link_indicators():
    body = ('<p>Click <a href="http://203.0.113.9/login">https://intranet.globex.example</a> or '
            '<a href="https://bit.ly/abc">here</a> or https://user@evil.example/x</p>')
    res = h.analyze(body)
    assert {"link_mismatch", "ip_url", "shortener", "userinfo_trick"} <= ids(res)


def test_language_indicators():
    res = h.analyze("Dear customer,\nYour account will be suspended. Verify your password within 24 hours. "
                    "Also buy gift cards. See invoice.zip and scan the QR code.")
    assert {"urgency", "credential_request", "payment_request", "generic_greeting", "risky_attachment",
            "qr_lure"} <= ids(res)
    assert res["verdict"] == "likely_phishing"


def test_legitimate_email_scores_low():
    raw = ("From: Team Lunch <events@globex.example>\nSubject: Friday lunch\n\n"
           "Hi Priya, lunch is in room 4 on Friday at 12:30. See you there! - Sam")
    res = h.analyze(raw)
    assert res["score"] < 20 and res["verdict"] == "likely_legitimate"


def test_report_phish_flow(learner, manager, db):
    r = learner.post("/api/v1/reports", json={"subject": "Mailbox almost full — action required",
                                              "raw_text": "From: it@umbre11a-corp.example\nSubject: Mailbox almost "
                                                          "full — action required\n\nVerify your account immediately"})
    assert r.status_code == 201
    rid = r.json()["id"]
    detail = learner.get(f"/api/v1/reports/{rid}").json()
    assert detail["heuristic_score"] is not None  # background triage ran
    assert detail["analysis"].get("suggested_status") == "confirmed_sim"  # matched a simulation template
    queue = manager.get("/api/v1/reports?status=new").json()
    assert any(i["id"] == rid for i in queue["items"])
    t = manager.post(f"/api/v1/reports/{rid}/triage", json={"status": "confirmed_sim", "feedback": "Nice catch!"})
    assert t.status_code == 200 and t.json()["status"] == "confirmed_sim"
    notes = learner.get("/api/v1/notifications?unread=true").json()["items"]
    assert any(n["kind"] == "report_feedback" for n in notes)
    other = __import__("tests.conftest", fromlist=["login"]).login("learner2@globex.example.com")
    assert other.get(f"/api/v1/reports/{rid}").status_code == 404
