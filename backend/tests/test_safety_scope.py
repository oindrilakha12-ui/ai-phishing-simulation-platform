"""Non-negotiable safety scope. These tests FAIL if:
  * a mail-sending library is imported or declared as a dependency,
  * a landing page / preview contains <input> or <form>,
  * a template lacks the watermark or red flags,
  * a non-fictional brand is used.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Template
from app.seed_data import TEMPLATES
from app.services.safety import WATERMARK, build_landing_page, build_preview_document, sanitize_html, validate_lure

APP_DIR = Path(__file__).resolve().parents[1] / "app"
REPO = Path(__file__).resolve().parents[2]
MAIL_MODULES = {"smtplib", "aiosmtplib", "sendgrid", "mailgun", "fastapi_mail", "flask_mail", "yagmail",
                "postmarker", "mailjet_rest", "emails", "redmail", "imaplib", "poplib"}


def test_no_mail_library_imported_anywhere():
    offenders = []
    for py in APP_DIR.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                root = n.split(".")[0]
                if root in MAIL_MODULES or n.startswith("email.mime"):
                    offenders.append(f"{py.name}: {n}")
    assert offenders == []


def test_no_mail_dependency_declared():
    reqs = (REPO / "backend" / "requirements.txt")
    if reqs.exists():
        names = {re.split(r"[=<>\[ ;]", line.strip(), maxsplit=1)[0].lower()
                 for line in reqs.read_text().splitlines() if line.strip() and not line.startswith("#")}
        assert not names & {m.replace("_", "-") for m in MAIL_MODULES} and not names & MAIL_MODULES
    pkg = REPO / "frontend" / "package.json"
    if pkg.exists():
        assert not re.search(r'"(nodemailer|@sendgrid/mail|mailgun\.js|resend|postmark)"', pkg.read_text())


@pytest.mark.parametrize("tmpl", TEMPLATES, ids=[t["name"] for t in TEMPLATES])
def test_seed_templates_are_watermarked_fictional_and_annotated(tmpl):
    assert WATERMARK in tmpl["body_html"]
    assert tmpl["red_flags"], "every template needs red flags"
    assert validate_lure(tmpl) == []


def test_all_stored_templates_are_safe(db):
    for t in db.scalars(select(Template)).all():
        assert WATERMARK in t.body_html, t.name
        assert t.red_flags, t.name


@pytest.mark.parametrize("tmpl", TEMPLATES[:3], ids=[t["name"] for t in TEMPLATES[:3]])
def test_landing_pages_and_previews_have_no_inputs_or_forms(tmpl):
    landing = build_landing_page(tmpl["name"], tmpl["red_flags"]).lower()
    doc, _ = build_preview_document(tmpl["subject"], tmpl["sender_name"], tmpl["sender_email"], tmpl["body_html"],
                                    tmpl["red_flags"])
    for html in (landing, doc.lower()):
        assert "<input" not in html and "<form" not in html and "<script" not in html
        assert WATERMARK.lower() in html


def test_sanitizer_strips_dangerous_markup_and_neutralises_links():
    dirty = ('<p onclick="x()">Hi</p><form action="http://x"><input name="pw"></form><script>alert(1)</script>'
             '<iframe src="http://x"></iframe><a href="http://evil.example/login">bank.example</a>')
    clean, links = sanitize_html(dirty)
    low = clean.lower()
    assert "<form" not in low and "<input" not in low and "<script" not in low and "<iframe" not in low
    assert "onclick" not in low
    assert 'href="#"' in clean and links[0]["href"] == "http://evil.example/login"


def test_real_brand_rejected():
    bad = dict(TEMPLATES[0], brand="PayPal")
    assert any("fictional" in p for p in validate_lure(bad))
    bad2 = dict(TEMPLATES[0], body_html=TEMPLATES[0]["body_html"] + "<p>Sign in to your Microsoft account</p>")
    assert any("real brand" in p for p in validate_lure(bad2))


def test_non_reserved_sender_and_links_rejected():
    assert validate_lure(dict(TEMPLATES[0], sender_email="it@globex.com"))
    assert validate_lure(dict(TEMPLATES[0], body_html=TEMPLATES[0]["body_html"] + '<a href="https://real.com">x</a>'))


def test_api_rejects_unsafe_templates(manager):
    base = {k: TEMPLATES[0][k] for k in ("name", "category", "difficulty", "subject", "sender_name",
                                         "sender_email", "body_html", "red_flags")}
    r = manager.post("/api/v1/templates", json={**base, "brand": "Amazon"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsafe_template"
    r = manager.post("/api/v1/templates", json={**base, "brand": "Globex", "red_flags": []})
    assert r.status_code == 422
    r = manager.post("/api/v1/templates", json={**base, "brand": "Globex",
                                                "body_html": "<p>Hello</p><form><input name=pw></form>"})
    assert r.status_code == 422


def test_api_repairs_missing_watermark_and_versions(manager):
    base = {k: TEMPLATES[0][k] for k in ("category", "difficulty", "subject", "sender_name", "sender_email",
                                         "red_flags")}
    r = manager.post("/api/v1/templates", json={**base, "name": "No watermark given", "brand": "Globex",
                                                "body_html": "<p>Dear employee, renew within 24 hours.</p>"})
    assert r.status_code == 201 and WATERMARK in r.json()["body_html"]
    tid = r.json()["id"]
    manager.patch(f"/api/v1/templates/{tid}", json={"subject": "Updated subject"})
    versions = manager.get(f"/api/v1/templates/{tid}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]


def test_synthetic_people_only(admin, db):
    from app.db.models import Target
    for email in db.scalars(select(Target.email)).all():
        assert email.endswith((".example", ".example.com")), email
    # There is deliberately no contact-import endpoint.
    paths = set(admin.get("/openapi.json").json()["paths"])
    assert not any("import" in p for p in paths)
    assert not any(re.search(r"send|smtp|mail", p) for p in paths)
