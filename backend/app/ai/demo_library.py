"""Hard-coded DEMO MODE content: 5 fictional training examples and a tips library.

Everything here uses fictional brands and reserved .example domains and is watermarked.
"""
from __future__ import annotations

from app.services.safety import WATERMARK

DEMO_EXAMPLES: list[dict] = [
    {
        "subject": "Action needed: confirm your Globex parking permit",
        "body_text": (
            "Dear employee,\n\nYour Globex parking permit expires today. To avoid losing your space, "
            "confirm your details within 24 hours at http://globex-parking.example/renew.\n\n"
            "Facilities Team"
        ),
        "fictional_brand": "Globex",
        "difficulty": "easy",
        "red_flags": [
            {"category": "greeting", "description": "Generic greeting instead of your name.", "cue": "Dear employee"},
            {"category": "urgency", "description": "Artificial deadline to rush you.", "cue": "within 24 hours"},
            {"category": "link", "description": "Link uses a look-alike domain, not the real intranet.",
             "cue": "globex-parking.example"},
        ],
    },
    {
        "subject": "Initech payroll: updated direct deposit form",
        "body_text": (
            "Hi,\n\nPayroll is migrating systems. Please reply with any changes to your bank details before "
            "Friday so your salary isn't delayed.\n\nInitech Payroll (sent from payroll-team@initech-hr.example)"
        ),
        "fictional_brand": "Initech",
        "difficulty": "medium",
        "red_flags": [
            {"category": "request", "description": "Asks for bank details by email reply.", "cue": "bank details"},
            {"category": "sender", "description": "Sender domain differs from the company's real domain.",
             "cue": "initech-hr.example"},
            {"category": "urgency", "description": "Threat that salary will be delayed.", "cue": "salary isn't delayed"},
        ],
    },
    {
        "subject": "Umbrella Corp shared a document with you",
        "body_text": (
            "A colleague shared 'Q3 bonus allocations.xlsm' with you. Open the file and enable editing to view "
            "it.\n\nUmbrella Corp Document Services"
        ),
        "fictional_brand": "Umbrella Corp",
        "difficulty": "medium",
        "red_flags": [
            {"category": "attachment", "description": "Macro-enabled file type (.xlsm) can run code.",
             "cue": "Q3 bonus allocations.xlsm"},
            {"category": "request", "description": "Asks you to enable editing/macros.", "cue": "enable editing"},
            {"category": "too_good", "description": "Bonus topic used as curiosity bait.", "cue": "bonus allocations"},
        ],
    },
    {
        "subject": "Re: invoice 4471 — revised remittance",
        "body_text": (
            "Hello,\n\nFollowing our call, Hooli Supplies has a new remittance account. Please send this week's "
            "payment there and keep this between us until the audit closes.\n\nRegards, Accounts (Hooli)"
        ),
        "fictional_brand": "Hooli",
        "difficulty": "hard",
        "red_flags": [
            {"category": "request", "description": "Change of payment account is a classic invoice-fraud sign.",
             "cue": "new remittance account"},
            {"category": "request", "description": "Asks for secrecy to stop you verifying.",
             "cue": "keep this between us"},
            {"category": "reply_to", "description": "Fake 'Re:' implies an earlier conversation that never happened.",
             "cue": "Following our call"},
        ],
    },
    {
        "subject": "Wi-Fi upgrade at Acme Corp — scan to reconnect",
        "body_text": (
            "The office Wi-Fi is being upgraded. Scan the QR code on the poster in the lobby with your phone to "
            "reconnect your device.\n\nAcme Corp IT"
        ),
        "fictional_brand": "Acme Corp",
        "difficulty": "hard",
        "red_flags": [
            {"category": "qr_code", "description": "QR codes hide the real destination URL.",
             "cue": "Scan the QR code"},
            {"category": "sender", "description": "Unannounced IT change not on the official channel.",
             "cue": "Acme Corp IT"},
        ],
    },
]

for ex in DEMO_EXAMPLES:
    ex["watermark"] = WATERMARK


TIPS_LIBRARY: list[dict] = [
    {"category": "link", "title": "Hover before you click",
     "body": "Hover over (or long-press) a link to reveal its real destination. If it doesn't match the sender's "
             "official domain exactly, don't open it."},
    {"category": "link", "title": "Look for look-alike domains",
     "body": "Attackers swap letters (rn for m, 0 for o) or add words like '-secure'. Read the domain right to "
             "left from the first single slash."},
    {"category": "sender", "title": "Check the real sender address",
     "body": "Display names are easy to fake. Expand the sender to see the actual address and its domain."},
    {"category": "sender", "title": "Verify through a second channel",
     "body": "If a colleague or supplier asks for something unusual, call them on a number you already have — "
             "never one from the email."},
    {"category": "urgency", "title": "Urgency is a red flag",
     "body": "'Within 24 hours' or 'account suspended' is designed to make you rush. Pause, breathe, verify."},
    {"category": "request", "title": "Never share credentials by email",
     "body": "No legitimate team will ask for your password or MFA code. Report any message that does."},
    {"category": "request", "title": "Payment changes need verification",
     "body": "Changes to bank details or urgent gift-card requests must be confirmed by phone with a known contact."},
    {"category": "attachment", "title": "Be careful with attachments",
     "body": "Unexpected .zip, .html, .iso or macro-enabled files can run code. Don't enable macros on files "
             "you didn't expect."},
    {"category": "qr_code", "title": "QR codes are links too",
     "body": "A QR code hides its URL. Preview the link your camera shows and avoid entering credentials after "
             "scanning."},
    {"category": "greeting", "title": "Generic greetings are a clue",
     "body": "'Dear customer' from a service that knows your name is a warning sign."},
    {"category": "reporting", "title": "Reporting is a win",
     "body": "Reporting a suspicious email protects everyone, even if it turns out to be safe. Use Report Phish."},
    {"category": "too_good", "title": "Too good to be true usually is",
     "body": "Surprise prizes, refunds or bonuses are common bait. Verify on the official site yourself."},
]


def tips_for(weak_categories: list[str], n: int = 3) -> list[dict]:
    """Pick n tips, prioritising the learner's weakest categories in order."""
    picked: list[dict] = []
    for cat in weak_categories:
        for tip in TIPS_LIBRARY:
            if tip["category"] == cat and tip not in picked:
                picked.append(tip)
                break
    for tip in TIPS_LIBRARY:  # fill with general tips
        if len(picked) >= n:
            break
        if tip not in picked and tip["category"] in ("reporting", "sender", "urgency", "link"):
            picked.append(tip)
    return [dict(t) for t in picked[:n]]
