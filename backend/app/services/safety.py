"""Safety-scope enforcement shared by templates, the AI generator and the preview sandbox.

Rules (also tested in tests/test_safety_scope.py):
  * Lures may only use FICTIONAL brands.
  * Every lure body carries the SIMULATION watermark.
  * Every lure has at least one annotated red flag.
  * Rendered HTML never contains forms, inputs, scripts, iframes or event handlers.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

WATERMARK = "SIMULATION — TRAINING ONLY"
WATERMARK_BANNER = (
    '<div class="pg-watermark" style="background:#b91c1c;color:#fff;font-weight:700;'
    'padding:6px 10px;text-align:center;letter-spacing:.05em">'
    f"{WATERMARK}</div>"
)

# Fictional brands only (classic TV/film fictional companies + our own inventions).
FICTIONAL_BRANDS = {
    "Globex", "Initech", "Umbrella Corp", "Acme Corp", "Hooli", "Vandelay Industries",
    "Wayne Enterprises", "Stark Industries", "Cyberdyne Systems", "Soylent Corp", "Contoso",
    "Northwind Traders", "Fabrikam", "Tailspin Toys", "Wonka Industries", "Oscorp",
}

# Real organizations a lure must never imitate. Used by the template validator and guardrail.
REAL_BRANDS = {
    "paypal", "microsoft", "office 365", "office365", "outlook", "google", "gmail", "apple", "icloud",
    "amazon", "aws", "netflix", "facebook", "meta", "instagram", "whatsapp", "linkedin", "twitter",
    "dropbox", "docusign", "adobe", "zoom", "slack", "salesforce", "fedex", "ups", "dhl", "usps",
    "chase", "wells fargo", "bank of america", "citibank", "citi", "hsbc", "barclays", "santander",
    "hdfc", "icici", "sbi", "state bank of india", "axis bank", "kotak", "paytm", "phonepe", "irs",
    "hmrc", "coinbase", "binance", "steam", "spotify", "ebay", "walmart", "visa", "mastercard",
    "american express", "amex", "github", "okta", "yahoo", "x.com", "tiktok", "flipkart", "airtel",
    "jio", "vodafone", "verizon", "at&t", "t-mobile", "lloyds", "natwest", "revolut", "venmo", "zelle",
}

# Allowed sender domains for lures: RFC 2606/6761 reserved names that can never be real.
RESERVED_TLDS = (".example", ".test", ".invalid", ".example.com", ".example.org", ".example.net")


def contains_real_brand(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({b for b in REAL_BRANDS if re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", lowered)})


def is_fictional_brand(brand: str) -> bool:
    return brand.strip().lower() in {b.lower() for b in FICTIONAL_BRANDS}


def is_reserved_domain(email_or_url: str) -> bool:
    host = email_or_url.split("@")[-1] if "@" in email_or_url and "//" not in email_or_url else (
        urlparse(email_or_url).hostname or "")
    host = host.lower().rstrip(".")
    return any(host == t.lstrip(".") or host.endswith(t) for t in RESERVED_TLDS)


def ensure_watermark(body_html: str) -> str:
    """Repair step: prepend the watermark banner if it is missing."""
    if WATERMARK in body_html:
        return body_html
    return WATERMARK_BANNER + body_html


# ------------------------------------------------------------------ HTML sanitizer

ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "div", "span", "h1",
                "h2", "h3", "h4", "table", "tr", "td", "th", "tbody", "thead", "hr", "small", "mark",
                "blockquote", "img"}
DROP_WITH_CONTENT = {"script", "style", "form", "input", "textarea", "select", "button", "iframe",
                     "object", "embed", "svg", "math", "template", "noscript", "link", "meta", "base"}
VOID_TAGS = {"input", "meta", "link", "base", "embed"}
SAFE_ATTRS ={"style", "class", "title", "alt", "data-flag", "colspan", "rowspan"}


class _Sanitizer(HTMLParser):
    """Allow-list sanitizer. Links are neutralised: the real href moves to data-actual-href and
    href becomes '#', so nothing in a preview can navigate anywhere."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0
        self.links: list[dict[str, Any]] = []
        self.in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_WITH_CONTENT:
            # Void elements (<input>, <meta>...) never get a closing tag, so they must not open a skip region.
            if tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED_TAGS:
            return
        clean: list[str] = []
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                continue
            if name == "style" and re.search(r"expression|url\s*\(|javascript", value, re.I):
                continue
            if name in SAFE_ATTRS:
                clean.append(f'{name}="{html.escape(value, quote=True)}"')
            elif tag == "a" and name == "href":
                idx = len(self.links)
                self.links.append({"index": idx, "href": value, "text": ""})
                clean.append(f'href="#" data-link-index="{idx}" data-actual-href="{html.escape(value, quote=True)}"')
            elif tag == "img" and name == "src" and value.startswith("data:image/"):
                clean.append(f'src="{html.escape(value, quote=True)}"')
        if tag == "a":
            self.in_link = True
        self.out.append(f"<{tag}{' ' if clean else ''}{' '.join(clean)}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID_TAGS:
                self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in ALLOWED_TAGS or tag in {"br", "hr", "img"}:
            return
        if tag == "a":
            self.in_link = False
        self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.links and self.in_link:
            self.links[-1]["text"] += data
        self.out.append(html.escape(data, quote=False))


def sanitize_html(raw: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (safe_html, links). links = [{index, href, text}] for the 'inspect link' feature."""
    p = _Sanitizer()
    p.feed(raw)
    p.close()
    return "".join(p.out), p.links


def link_report(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare what a link SAYS (its text) with where it GOES (its href)."""
    report = []
    for link in links:
        href_host = (urlparse(link["href"]).hostname or "").lower()
        text = link["text"].strip()
        shown_host = ""
        m = re.search(r"([a-z0-9-]+\.)+[a-z]{2,}", text.lower())
        if m:
            shown_host = m.group(0)
        mismatch = bool(shown_host) and bool(href_host) and not (
            href_host == shown_host or href_host.endswith("." + shown_host))
        report.append({**link, "actual_host": href_host, "displayed_host": shown_host or None,
                       "mismatch": mismatch})
    return report


def highlight_cues(body_html: str, red_flags: list[dict[str, Any]]) -> str:
    """Wrap each red flag's `cue` text in <mark data-flag="id"> so the UI can highlight it on hover.
    Works on already-sanitized HTML and only replaces inside text (not inside tags)."""
    out = body_html
    for flag in red_flags:
        cue = (flag.get("cue") or "").strip()
        if not cue:
            continue
        escaped = html.escape(cue, quote=False)
        # Replace the first occurrence that is not inside a tag.
        pattern = re.compile(rf"(>[^<]*?)({re.escape(escaped)})", re.I)
        flag_id = html.escape(str(flag["id"]))
        out = pattern.sub(lambda m, fid=flag_id: f'{m.group(1)}<mark data-flag="{fid}">{m.group(2)}</mark>',
                          out, count=1)
    return out


PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def build_preview_document(subject: str, sender_name: str, sender_email: str, body_html: str,
                           red_flags: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Return a self-contained HTML document for a sandboxed iframe (srcdoc) + the link report."""
    safe_body, links = sanitize_html(ensure_watermark(body_html))
    safe_body = highlight_cues(safe_body, red_flags)
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{PREVIEW_CSP}">
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;color:#111;background:#fff;font-size:14px}}
.hdr{{border-bottom:1px solid #ddd;padding:10px 14px;background:#f8fafc}}
.hdr div{{margin:2px 0}} .body{{padding:14px}}
mark{{background:transparent;transition:background .15s}}
mark.pg-active{{background:#fde047;outline:2px solid #ca8a04;border-radius:2px}}
a{{color:#1d4ed8}}
</style></head><body>
<div class="hdr"><div><b>From:</b> {html.escape(sender_name)} &lt;{html.escape(sender_email)}&gt;</div>
<div><b>Subject:</b> {html.escape(subject)}</div></div>
<div class="body">{safe_body}</div></body></html>"""
    return doc, link_report(links)


def build_landing_page(template_name: str, red_flags: list[dict[str, Any]]) -> str:
    """Static, field-less educational landing page shown after a simulated click."""
    items = "".join(
        f"<li><b>{html.escape(f.get('category', 'cue'))}:</b> {html.escape(f.get('description', ''))}</li>"
        for f in red_flags)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{PREVIEW_CSP}">
<title>{WATERMARK}</title></head>
<body style="font-family:system-ui,Arial,sans-serif;max-width:680px;margin:24px auto;padding:0 16px">
{WATERMARK_BANNER}
<h1>This was a training simulation</h1>
<p>You opened a simulated link from <b>{html.escape(template_name)}</b>. Nothing was collected and
no real site was involved. Here are the red flags you missed:</p>
<ul>{items}</ul>
<p>Next time: pause, inspect the sender and link, and use the <b>Report Phish</b> button.</p>
</body></html>"""


def validate_lure(data: dict[str, Any]) -> list[str]:
    """Return a list of safety violations for a lure/template dict (empty == safe)."""
    problems: list[str] = []
    if not is_fictional_brand(data.get("brand", "")):
        problems.append(f"brand '{data.get('brand')}' is not on the fictional-brand allow-list")
    text_blob = " ".join(str(data.get(k, "")) for k in ("subject", "sender_name", "body_html", "brand", "name"))
    real = contains_real_brand(text_blob)
    if real:
        problems.append(f"mentions real brand(s): {', '.join(real)}")
    if not data.get("red_flags"):
        problems.append("at least one annotated red flag is required")
    sender = data.get("sender_email", "")
    if sender and not is_reserved_domain(sender):
        problems.append("sender_email must use a reserved domain (.example / .test / .invalid)")
    body = data.get("body_html", "")
    if re.search(r"<\s*(form|input|textarea|select|button|script|iframe)\b", body, re.I):
        problems.append("body must not contain forms, inputs, buttons, scripts or iframes")
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)', body, re.I):
        if href.startswith(("http://", "https://")) and not is_reserved_domain(href):
            problems.append(f"link '{href}' must point to a reserved domain")
    return problems
