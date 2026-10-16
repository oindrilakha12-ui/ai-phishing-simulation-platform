"""Deterministic (non-LLM) phishing indicators for the defensive Indicator Analyst.

Input: a pasted raw email (headers + body) or just a body. Output: a 0-100 suspicion
score plus explained indicators. Every check is a pure function so it is easy to test.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from email import message_from_string
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

SEVERITY_POINTS = {"low": 6, "medium": 14, "high": 24}

URGENCY_PATTERNS = [
    r"\burgent\b", r"\bimmediately\b", r"\bwithin (24|48) hours\b", r"\bact now\b", r"\bfinal (notice|warning)\b",
    r"\baccount (will be )?(suspended|locked|closed|deactivated)\b", r"\bverify (your )?(account|identity)\b",
    r"\bexpires? (today|soon)\b", r"\blast chance\b", r"\bunusual (sign-?in|activity)\b",
]
CREDENTIAL_PATTERNS = [
    r"\b(confirm|update|verify|re-?enter) (your )?(password|credentials|login|banking details|card)\b",
    r"\bpassword\b.*\b(expire|reset)\b", r"\bsign in to (keep|restore|avoid)\b",
]
PAYMENT_PATTERNS = [r"\bgift ?cards?\b", r"\bwire transfer\b", r"\bchange (of )?bank(ing)? details\b",
                    r"\binvoice (attached|overdue)\b", r"\bpayment (failed|declined|overdue)\b"]
GENERIC_GREETINGS = [r"^\s*(dear|hello|hi)\s+(customer|user|member|client|sir|madam|valued \w+|account holder)\b",
                     r"^\s*dear\s+[\w.+-]+@"]
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly"}
RISKY_EXTENSIONS = (".exe", ".scr", ".js", ".vbs", ".bat", ".cmd", ".iso", ".img", ".html", ".htm", ".zip",
                    ".docm", ".xlsm", ".lnk", ".hta")

# Well-known domains that attackers imitate (used only for DETECTING lookalikes).
PROTECTED_DOMAINS = [
    "paypal.com", "microsoft.com", "office.com", "outlook.com", "google.com", "apple.com", "amazon.com",
    "netflix.com", "linkedin.com", "dropbox.com", "docusign.com", "chase.com", "wellsfargo.com",
    "bankofamerica.com", "dhl.com", "fedex.com", "github.com", "okta.com", "adobe.com", "zoom.us",
    # fictional org domains used in this demo
    "globex.example", "initech.example", "umbrella.example",
]

# Visually confusable characters -> ASCII skeleton (subset of Unicode confusables).
HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ԁ": "d",
    "ɡ": "g", "ո": "n", "ѕ": "s", "ӏ": "l", "0": "o", "1": "l", "3": "e", "5": "s", "@": "a", "$": "s",
})


@dataclass
class Indicator:
    id: str
    title: str
    severity: str  # low | medium | high
    explanation: str
    evidence: str = ""
    category: str = "other"


# ------------------------------------------------------------------ helpers

class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append(("".join(self._text).strip(), self._href))
            self._href = None


def extract_links(body: str) -> list[tuple[str, str]]:
    """Return (displayed_text, actual_href) pairs from HTML anchors and markdown-style [text](url)."""
    p = _LinkParser()
    try:
        p.feed(body)
    except Exception:  # noqa: BLE001 - malformed HTML is common in phishing
        pass
    links = list(p.links)
    links += re.findall(r"\[([^\]]{1,200})\]\((https?://[^\s)]+)\)", body)
    bare = re.findall(r"(?<![\"'=(])\bhttps?://[^\s<>\"')]+", body)
    known = {h for _, h in links}
    links += [(u, u) for u in bare if u not in known]
    return links


def domain_of(value: str) -> str:
    value = value.strip().lower()
    if "@" in value and "//" not in value:
        return value.rsplit("@", 1)[-1].strip(">").strip()
    return (urlparse(value if "//" in value else "//" + value).hostname or "").strip(".")


def registrable(domain: str) -> str:
    """Approximate registrable domain (last two labels; good enough for heuristics)."""
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def skeleton(domain: str) -> str:
    d = unicodedata.normalize("NFKC", domain.lower()).translate(HOMOGLYPHS)
    return d.replace("rn", "m").replace("vv", "w")


def levenshtein(a: str, b: str) -> int:
    """Classic dynamic-programming edit distance, O(len(a)*len(b)) time, O(len(b)) memory."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lookalike_of(domain: str) -> str | None:
    """Return the protected domain this one imitates, or None."""
    if not domain:
        return None
    reg = registrable(domain)
    if reg in PROTECTED_DOMAINS or domain in PROTECTED_DOMAINS:
        return None
    sk = skeleton(reg)
    label = reg.split(".")[0]
    for real in PROTECTED_DOMAINS:
        real_label = real.split(".")[0]
        if sk == skeleton(real) or skeleton(label) == real_label:
            return real
        if len(real_label) >= 5 and levenshtein(label, real_label) <= (1 if len(real_label) < 8 else 2):
            return real
        # brand embedded in a different domain, e.g. paypal-security-check.com / login.microsoft.verify.io
        if len(real_label) >= 5 and real_label in skeleton(domain) and reg != real:
            return real
    if domain.startswith("xn--") or ".xn--" in domain:
        return "(punycode / internationalised domain)"
    return None


# ------------------------------------------------------------------ parsing

def parse_email(raw: str) -> dict[str, Any]:
    """Split a pasted email into headers and body. Works with body-only input too."""
    raw = raw.replace("\r\n", "\n")
    looks_like_headers = bool(re.match(r"^[A-Za-z-]+:\s", raw.lstrip()))
    if looks_like_headers:
        msg = message_from_string(raw.lstrip())
        if msg.is_multipart():
            parts = [p.get_payload(decode=True) for p in msg.walk() if p.get_content_maintype() == "text"]
            body = "\n".join(p.decode(errors="replace") for p in parts if p)
        else:
            payload = msg.get_payload(decode=True)
            body = payload.decode(errors="replace") if isinstance(payload, bytes) else str(msg.get_payload())
        headers = {k.lower(): str(v) for k, v in msg.items()}
        attachments = [p.get_filename() for p in msg.walk() if p.get_filename()] if msg.is_multipart() else []
        auth_results = " ".join(str(v) for k, v in msg.items() if k.lower() in
                                ("authentication-results", "arc-authentication-results", "received-spf"))
    else:
        body, headers, attachments, auth_results = raw, {}, [], ""
    attachments += re.findall(r"\b[\w-]+\.(?:exe|scr|js|vbs|bat|cmd|iso|img|html?|zip|docm|xlsm|lnk|hta)\b",
                              body, re.I)
    return {"headers": headers, "body": body, "attachments": attachments, "auth_results": auth_results}


def parse_auth_results(text: str) -> dict[str, str]:
    """Extract spf/dkim/dmarc verdicts from Authentication-Results style headers."""
    out = {}
    for mech in ("spf", "dkim", "dmarc"):
        m = re.search(rf"\b{mech}\s*=\s*([a-z]+)", text, re.I)
        if m:
            out[mech] = m.group(1).lower()
    if "spf" not in out:
        m = re.match(r"\s*(pass|fail|softfail|neutral|none|permerror|temperror)\b", text, re.I)
        if m:
            out["spf"] = m.group(1).lower()
    return out


# ------------------------------------------------------------------ main entry

def analyze(raw: str) -> dict[str, Any]:
    parsed = parse_email(raw)
    h, body = parsed["headers"], parsed["body"]
    text = re.sub(r"<[^>]+>", " ", body)
    lowered = text.lower()
    found: list[Indicator] = []

    # --- authentication results
    auth = parse_auth_results(parsed["auth_results"])
    for mech, verdict in auth.items():
        if verdict in ("fail", "softfail", "permerror"):
            sev = "high" if mech == "dmarc" or verdict == "fail" else "medium"
            found.append(Indicator(f"auth_{mech}", f"{mech.upper()} {verdict}", sev,
                                   f"The receiving server reported {mech.upper()}={verdict}: the message may not "
                                   f"really come from the domain it claims.", f"{mech}={verdict}", "sender"))

    # --- sender checks
    from_name, from_addr = parseaddr(h.get("from", ""))
    _, reply_addr = parseaddr(h.get("reply-to", ""))
    _, return_path = parseaddr(h.get("return-path", ""))
    from_dom = domain_of(from_addr) if from_addr else ""
    if reply_addr and from_dom and registrable(domain_of(reply_addr)) != registrable(from_dom):
        found.append(Indicator("reply_to_mismatch", "Reply-To differs from From", "high",
                               "Replies would go to a different domain than the apparent sender.",
                               f"From: {from_addr} / Reply-To: {reply_addr}", "reply_to"))
    if return_path and from_dom and registrable(domain_of(return_path)) != registrable(from_dom):
        found.append(Indicator("return_path_mismatch", "Return-Path differs from From", "low",
                               "The envelope sender domain differs from the visible sender (common for "
                               "mailing services, but worth a look).", f"Return-Path: {return_path}", "sender"))
    if from_name and from_dom:
        named = re.search(r"([a-z0-9-]+\.[a-z]{2,})", from_name.lower())
        if named and registrable(named.group(1)) != registrable(from_dom):
            found.append(Indicator("display_name_spoof", "Display name shows a different domain", "high",
                                   "The sender's display name contains a domain that doesn't match the real address.",
                                   f"{from_name} <{from_addr}>", "sender"))
    if from_dom:
        imitated = lookalike_of(from_dom)
        if imitated:
            found.append(Indicator("lookalike_sender", "Lookalike sender domain", "high",
                                   f"'{from_dom}' looks deceptively similar to '{imitated}'.", from_dom, "sender"))
        if from_dom in ("gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "proton.me") and re.search(
                r"\b(it|helpdesk|payroll|hr|security|support|ceo|finance)\b", (from_name or "").lower()):
            found.append(Indicator("freemail_official", "Official-sounding sender on a free webmail domain",
                                   "medium", "Corporate departments rarely email from free webmail accounts.",
                                   f"{from_name} <{from_addr}>", "sender"))

    # --- links
    links = extract_links(body)
    link_details = []
    for shown, href in links[:50]:
        actual = domain_of(href)
        shown_dom = domain_of(shown) if re.search(r"[a-z0-9-]+\.[a-z]{2,}", shown.lower()) else ""
        detail = {"displayed": shown[:200], "actual": href[:300], "actual_domain": actual, "issues": []}
        if shown_dom and actual and registrable(shown_dom) != registrable(actual):
            detail["issues"].append("display/actual mismatch")
            found.append(Indicator("link_mismatch", "Link text and destination differ", "high",
                                   "The link shows one address but actually goes somewhere else.",
                                   f"shows {shown_dom} → goes to {actual}", "link"))
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", actual):
            detail["issues"].append("raw IP address")
            found.append(Indicator("ip_url", "Link points to a raw IP address", "high",
                                   "Legitimate services almost never link to bare IP addresses.", actual, "link"))
        if actual in SHORTENERS:
            detail["issues"].append("URL shortener")
            found.append(Indicator("shortener", "Shortened link hides destination", "medium",
                                   "URL shorteners hide where a link really goes.", href, "link"))
        imitated = lookalike_of(actual)
        if imitated:
            detail["issues"].append(f"lookalike of {imitated}")
            found.append(Indicator("lookalike_link", "Lookalike link domain", "high",
                                   f"'{actual}' imitates '{imitated}'.", actual, "link"))
        if href.lower().startswith("http://"):
            detail["issues"].append("not HTTPS")
        if "@" in urlparse(href).netloc:
            detail["issues"].append("userinfo @ trick")
            found.append(Indicator("userinfo_trick", "'@' trick in URL", "high",
                                   "Everything before '@' in a URL is ignored by the browser — a classic disguise.",
                                   href, "link"))
        link_details.append(detail)

    # --- language heuristics
    for pattern_list, ind_id, title, sev, cat, why in (
        (URGENCY_PATTERNS, "urgency", "Urgency or threat language", "medium", "urgency",
         "Pressure to act fast is designed to stop you thinking carefully."),
        (CREDENTIAL_PATTERNS, "credential_request", "Asks for credentials or sensitive details", "high", "request",
         "Legitimate organisations don't ask you to confirm passwords or card details by email."),
        (PAYMENT_PATTERNS, "payment_request", "Unusual payment request", "high", "request",
         "Gift cards, wire transfers and bank-detail changes are hallmarks of fraud / BEC."),
    ):
        hits = [m.group(0) for p in pattern_list for m in [re.search(p, lowered)] if m]
        if hits:
            found.append(Indicator(ind_id, title, sev, why, ", ".join(sorted(set(hits)))[:200], cat))
    for p in GENERIC_GREETINGS:
        m = re.search(p, lowered, re.M)
        if m:
            found.append(Indicator("generic_greeting", "Generic greeting", "low",
                                   "Messages from services you use normally address you by name.",
                                   m.group(0).strip(), "greeting"))
            break
    risky = [a for a in parsed["attachments"] if a and a.lower().endswith(RISKY_EXTENSIONS)]
    if risky:
        found.append(Indicator("risky_attachment", "Risky attachment type", "high",
                               "Executable, script, archive and macro-enabled files are common malware carriers.",
                               ", ".join(sorted(set(risky)))[:200], "attachment"))
    if re.search(r"\bqr[- ]?code\b|\bscan (the|this) code\b", lowered):
        found.append(Indicator("qr_lure", "Asks you to scan a QR code", "medium",
                               "QR codes hide the destination URL and move you to a less-protected phone.",
                               "QR code mention", "qr_code"))
    if re.search(r"\b(you('ve| have) won|lottery|claim your (prize|reward)|free (iphone|gift))\b", lowered):
        found.append(Indicator("too_good", "Too good to be true", "medium",
                               "Unexpected prizes and rewards are bait.", "prize language", "too_good"))

    # de-duplicate by id (keep the first evidence, count occurrences)
    unique: dict[str, Indicator] = {}
    for ind in found:
        unique.setdefault(ind.id, ind)
    indicators = list(unique.values())
    score = min(100, sum(SEVERITY_POINTS[i.severity] for i in indicators))
    verdict = "likely_phishing" if score >= 45 else "suspicious" if score >= 20 else "likely_legitimate"
    return {
        "score": score,
        "verdict": verdict,
        "indicators": [asdict(i) for i in sorted(indicators, key=lambda i: -SEVERITY_POINTS[i.severity])],
        "auth_results": auth,
        "links": link_details,
        "sender": {"from": from_addr, "display_name": from_name, "reply_to": reply_addr or None,
                   "return_path": return_path or None},
        "attachments": parsed["attachments"],
        "method": "deterministic_heuristics",
    }
