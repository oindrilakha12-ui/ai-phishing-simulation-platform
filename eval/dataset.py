"""Labelled SYNTHETIC email dataset for evaluating the Indicator Analyst.

Emails are assembled from small building blocks with a fixed seed, so the dataset is
reproducible. Label 1 = phishing-style, 0 = legitimate. Includes deliberately HARD cases:
phishing with few technical tells (plain-text invoice fraud) and legitimate mail with
urgency words or newsletters with many links, so the metrics are not trivially perfect.
All domains are fictional or RFC 2606 reserved.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "data" / "emails.jsonl"

NAMES = ["Priya", "Sam", "Alex", "Jordan", "Mei", "Omar", "Lucia", "Tom"]
ORG = "globex.example"

PHISH_SENDERS = [
    ('"IT Service Desk" <helpdesk@g1obex-support.example>', None),
    ('"Payroll" <payroll@globex-hr.example>', "payroll-team@mailbox-relay.example"),
    ('"Globex Security" <security@globex.example.attacker.example>', None),
    ('"accounts@globex.example" <billing@invoices-portal.example>', "refunds@other-domain.example"),
    ('"CEO Office" <ceo.office@freemail.example>', "ceo.private@freemail.example"),
    ('"Microsoft 365" <no-reply@rnicrosoft-alerts.example>', None),
]
PHISH_AUTH = ["spf=fail; dkim=none; dmarc=fail", "spf=softfail; dkim=fail; dmarc=fail", "spf=pass; dkim=pass; dmarc=pass", ""]
PHISH_BODIES = [
    "Dear user,\nYour mailbox will be suspended within 24 hours. Verify your account immediately:\n"
    '<a href="http://203.0.113.{n}/login">https://portal.globex.example</a>',
    "Hello,\nWe noticed unusual sign-in activity. Confirm your password here: https://bit.ly/g{n}x",
    "Dear customer,\nPayment failed for invoice {n}. Update your banking details today or service ends. See invoice_{n}.html",
    "Hi,\nI need you to buy 5 gift cards for a client urgently. Keep this between us. Reply with the codes.",
    "Your parcel is on hold. Scan the QR code in the attached PDF to schedule delivery within 48 hours.",
    "Congratulations, you have won a reward! Claim your prize at http://user@prize-claim.example/{n}",
    # hard: few technical tells
    "Hi {name},\nFollowing up on our call, please process this week's supplier payment to the new account we discussed. Thanks.",
    "Hello {name}, the shared document is ready. Open Q3_report.zip to review before the meeting.",
]
LEGIT_SENDERS = ['"Team Events" <events@globex.example>', '"IT Updates" <it-news@globex.example>',
                 '"HR" <hr@globex.example>', '"Facilities" <facilities@globex.example>',
                 '"Newsletter" <news@globex.example>']
LEGIT_BODIES = [
    "Hi {name},\nLunch is in room 4 on Friday at 12:30. See you there!\nSam",
    "Hi all,\nThe office will be closed on Monday for maintenance. No action needed.",
    "Hello {name},\nYour annual leave request for {n} March has been approved. Enjoy your break.",
    "Reminder: the quarterly town hall starts at 3pm. The agenda is on the intranet home page.",
    "Hi {name},\nThanks for presenting today. Slides are in the team folder as usual.",
    # hard legit: urgency + links but genuine
    "Urgent: the fire drill is today at 11am. Please follow the wardens' instructions. Details: https://intranet.globex.example/safety",
    'This week\'s newsletter: <a href="https://intranet.globex.example/news/{n}">intranet.globex.example/news</a> and '
    '<a href="https://intranet.globex.example/events">events calendar</a>.',
    "Hi {name}, your password will expire in 7 days. Change it from the usual settings page on your laptop (do not use email links).",
]


def build(n_phish: int = 64, n_legit: int = 56, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n_phish):
        sender, reply = rng.choice(PHISH_SENDERS)
        auth = rng.choice(PHISH_AUTH)
        body = rng.choice(PHISH_BODIES).format(n=rng.randint(10, 250), name=rng.choice(NAMES))
        hdr = (f"Authentication-Results: mx.{ORG}; {auth}\n" if auth else "") + f"From: {sender}\n"
        if reply:
            hdr += f"Reply-To: {reply}\n"
        rows.append({"id": f"p{i}", "label": 1, "raw": f"{hdr}Subject: Notice {i}\n\n{body}"})
    for i in range(n_legit):
        sender = rng.choice(LEGIT_SENDERS)
        body = rng.choice(LEGIT_BODIES).format(n=rng.randint(1, 28), name=rng.choice(NAMES))
        hdr = f"Authentication-Results: mx.{ORG}; spf=pass; dkim=pass; dmarc=pass\nFrom: {sender}\n"
        rows.append({"id": f"l{i}", "label": 0, "raw": f"{hdr}Subject: Update {i}\n\n{body}"})
    rng.shuffle(rows)
    return rows


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = build()
    OUT.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} labelled synthetic emails to {OUT}")
