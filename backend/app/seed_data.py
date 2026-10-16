"""Static seed content: training templates (fictional, watermarked) and LMS modules."""
from __future__ import annotations

from app.services.safety import WATERMARK_BANNER

TEMPLATES: list[dict] = [
    {
        "name": "Parking permit renewal", "brand": "Globex", "category": "credentials", "difficulty": "easy",
        "subject": "Action needed: renew your parking permit",
        "sender_name": "Globex Facilities", "sender_email": "facilities@globex-parking.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Dear employee,</p><p>Your parking permit expires <b>today</b>. Renew within 24 hours to keep "
            "your space.</p><p><a href=\"http://globex-parking.example/renew\">intranet.globex.example/parking</a>"
            "</p><p>Facilities Team</p>"),
        "red_flags": [
            {"id": "f1", "category": "greeting", "description": "Generic greeting instead of your name.",
             "cue": "Dear employee"},
            {"id": "f2", "category": "urgency", "description": "Artificial deadline.", "cue": "within 24 hours"},
            {"id": "f3", "category": "link", "description": "Link text shows the intranet, but goes to another domain.",
             "cue": "intranet.globex.example/parking"},
        ],
    },
    {
        "name": "Shared document notification", "brand": "Initech", "category": "attachments", "difficulty": "easy",
        "subject": "A file has been shared with you",
        "sender_name": "Initech Docs", "sender_email": "no-reply@initech-docs.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Hello,</p><p>A colleague shared <b>Salary_Review_2026.html</b> with you. Open the attachment "
            "to view it.</p><p><a href=\"http://initech-docs.example/view\">Open document</a></p>"),
        "red_flags": [
            {"id": "f1", "category": "attachment", "description": "HTML attachments can imitate login pages.",
             "cue": "Salary_Review_2026.html"},
            {"id": "f2", "category": "too_good", "description": "Salary topic used as curiosity bait.",
             "cue": "Salary_Review"},
            {"id": "f3", "category": "sender", "description": "Sender domain is not the company's real domain.",
             "cue": "Hello,"},
        ],
    },
    {
        "name": "IT mailbox quota", "brand": "Umbrella Corp", "category": "credentials", "difficulty": "medium",
        "subject": "Mailbox almost full — action required",
        "sender_name": "Umbrella Corp IT Service Desk", "sender_email": "it-servicedesk@umbre11a-corp.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Hi,</p><p>Your mailbox is at 98% capacity. Messages may be rejected. Increase your quota "
            "through the service portal:</p><p><a href=\"http://umbre11a-corp.example/quota\">"
            "portal.umbrella.example</a></p><p>IT Service Desk</p>"),
        "red_flags": [
            {"id": "f1", "category": "sender", "description": "Look-alike domain: 'umbre11a' uses the digit 1 for l.",
             "cue": "IT Service Desk"},
            {"id": "f2", "category": "urgency", "description": "Threat that messages will be rejected.",
             "cue": "Messages may be rejected"},
            {"id": "f3", "category": "link", "description": "Displayed portal address differs from the real link.",
             "cue": "portal.umbrella.example"},
        ],
    },
    {
        "name": "Payroll bank details update", "brand": "Initech", "category": "bec", "difficulty": "medium",
        "subject": "Payroll system migration",
        "sender_name": "Initech Payroll", "sender_email": "payroll@initech-hr.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Hi,</p><p>We are moving to a new payroll provider. Please reply with your updated bank details "
            "before Friday so your salary is not delayed.</p><p>Payroll Team</p>"),
        "red_flags": [
            {"id": "f1", "category": "request", "description": "Asks for bank details by email.",
             "cue": "updated bank details"},
            {"id": "f2", "category": "urgency", "description": "Threat of a delayed salary.",
             "cue": "salary is not delayed"},
            {"id": "f3", "category": "sender", "description": "HR domain differs from the company's real domain.",
             "cue": "Payroll Team"},
        ],
    },
    {
        "name": "Supplier remittance change", "brand": "Hooli", "category": "bec", "difficulty": "hard",
        "subject": "Re: invoice 4471",
        "sender_name": "Hooli Accounts", "sender_email": "accounts@hooli-billing.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Hello,</p><p>Following our call, our remittance account has changed. Please use the new details "
            "for this week's payment and keep this confidential until our audit closes.</p>"
            "<p>Kind regards,<br>Accounts</p>"),
        "red_flags": [
            {"id": "f1", "category": "request", "description": "A change of payment account must be verified by phone.",
             "cue": "remittance account has changed"},
            {"id": "f2", "category": "request", "description": "Secrecy stops you from verifying.",
             "cue": "keep this confidential"},
            {"id": "f3", "category": "reply_to", "description": "Fake 'Re:' implies a conversation that never happened.",
             "cue": "Following our call"},
        ],
    },
    {
        "name": "Wi-Fi QR re-registration", "brand": "Acme Corp", "category": "qr_code", "difficulty": "hard",
        "subject": "Office Wi-Fi upgrade this week",
        "sender_name": "Acme Corp Workplace", "sender_email": "workplace@acme-wifi.example",
        "body_html": WATERMARK_BANNER + (
            "<p>Hi team,</p><p>We are upgrading the office Wi-Fi. Scan the QR code on the lobby poster with your "
            "phone and sign in again to keep access.</p><p>Workplace Team</p>"),
        "red_flags": [
            {"id": "f1", "category": "qr_code", "description": "QR codes hide the destination URL.",
             "cue": "Scan the QR code"},
            {"id": "f2", "category": "request", "description": "Asks you to sign in after scanning.",
             "cue": "sign in again"},
            {"id": "f3", "category": "sender", "description": "Unannounced change from an unfamiliar domain.",
             "cue": "Workplace Team"},
        ],
    },
]

MODULES: list[dict] = [
    {
        "title": "Phishing Basics", "category": "basics", "est_minutes": 6,
        "description": "What phishing is and the five checks that catch most of it.",
        "lessons": [
            ("What is phishing?", "Phishing is a message designed to trick you into clicking, sharing "
             "information or paying. It arrives by email, text, phone or even QR code.\n\nAttackers rely on "
             "**emotion** (fear, curiosity, urgency) more than technology."),
            ("The five checks", "1. **Sender**: is the address really who it claims?\n2. **Links**: hover to "
             "see the real destination.\n3. **Urgency**: is someone rushing you?\n4. **Request**: are they "
             "asking for credentials, payment or data?\n5. **Context**: were you expecting this?"),
            ("Report, don't delete", "Reporting helps the security team protect everyone. Use **Report Phish** "
             "and never forward suspicious emails to colleagues."),
        ],
        "questions": [
            ("Which emotion do phishing emails most often exploit?", ["Boredom", "Urgency or fear", "Nostalgia"],
             1, "Urgency and fear push you to act before thinking."),
            ("What should you do with a suspicious email?", ["Delete it", "Forward it to colleagues",
                                                             "Report it with Report Phish"], 2,
             "Reporting lets the security team investigate and warn others."),
            ("A generic greeting like 'Dear customer' is…", ["A possible red flag", "Always safe", "Required by law"],
             0, "Services you use usually know your name."),
        ],
    },
    {
        "title": "Links and Look-alike Domains", "category": "links", "est_minutes": 7,
        "description": "Read URLs like a pro and spot domain tricks.",
        "lessons": [
            ("Hover before you click", "Hovering (or long-pressing on mobile) reveals the real destination. "
             "If the text says one address and the link goes elsewhere, stop."),
            ("Reading a domain", "Read from the first single slash **backwards**. In "
             "`login.globex.example.evil.example/path`, the real domain is `evil.example`."),
            ("Look-alike tricks", "Watch for swapped characters (`rn` → `m`, `0` → `o`, `1` → `l`), extra words "
             "(`-secure`, `-support`) and international characters that look like Latin letters."),
        ],
        "questions": [
            ("What is the real domain of login.globex.example.evil.example/x?",
             ["globex.example", "evil.example", "login.globex"], 1, "Read right-to-left from the first single slash."),
            ("'umbre11a.example' imitates 'umbrella.example' by…", ["Using digits for letters", "Using HTTPS",
                                                                    "Being shorter"], 0,
             "Digit 1 looks like the letter l."),
            ("The link text says one site, the hover shows another. You should…",
             ["Click to check", "Not click and report", "Reply to ask"], 1, "Mismatched links are a strong red flag."),
        ],
    },
    {
        "title": "Who Is Really Sending This?", "category": "sender", "est_minutes": 5,
        "description": "Display names, Reply-To tricks and verifying through a second channel.",
        "lessons": [
            ("Display names lie", "Anyone can set the display name to 'CEO' or 'IT Support'. Always expand the "
             "sender to see the actual address."),
            ("Reply-To mismatch", "If the Reply-To address differs from the From address, your reply goes "
             "somewhere else — common in invoice fraud."),
        ],
        "questions": [
            ("A display name can be set to anything by the sender.", ["True", "False"], 0,
             "Display names are not verified."),
            ("From: ceo@globex.example, Reply-To: ceo@globex-mail.example. This is…",
             ["Normal", "A red flag"], 1, "Replies would go to a different domain."),
        ],
    },
    {
        "title": "Social Engineering and Payment Fraud", "category": "social_engineering", "est_minutes": 8,
        "description": "Urgency, authority, secrecy and payment-change scams.",
        "lessons": [
            ("Pressure tactics", "Urgency ('within 1 hour'), authority ('the CEO needs this') and secrecy "
             "('keep this between us') are designed to stop you verifying."),
            ("Payment changes", "Always verify bank-detail changes and unusual payment requests by **phone** "
             "using a number you already have, never one from the email."),
        ],
        "questions": [
            ("A supplier emails new bank details. You should…", ["Update them", "Verify by phone using a known number",
                                                                 "Reply asking if it's real"], 1,
             "Verify out-of-band with contact details you already trust."),
            ("Requests for gift cards from an executive are…", ["Normal", "A classic scam"], 1,
             "Executives don't ask staff to buy gift cards by email."),
        ],
    },
    {
        "title": "Dangerous Attachments", "category": "attachments", "est_minutes": 5,
        "description": "Which file types are risky and why.",
        "lessons": [
            ("Risky file types", "Be wary of `.html`, `.zip`, `.iso`, `.exe`, `.js` and macro-enabled Office files "
             "(`.docm`, `.xlsm`) you didn't expect."),
            ("Enable content?", "If a document asks you to 'Enable editing' or 'Enable content' to view it, "
             "close it and report it."),
        ],
        "questions": [
            ("Which file type is most likely to run code?", [".txt", ".xlsm", ".png"], 1,
             "Macro-enabled Office files can run code."),
            ("A document asks you to 'Enable content' to read it. You…", ["Enable it", "Close and report"], 1,
             "Legitimate documents rarely need macros to be read."),
        ],
    },
    {
        "title": "QR Codes and Mobile Phishing", "category": "qr_code", "est_minutes": 5,
        "description": "Quishing, smishing and safe scanning habits.",
        "lessons": [
            ("Why QR codes are risky", "You can't read a QR code's destination before scanning, and it moves you "
             "onto your phone."),
            ("Safe scanning", "Check the URL preview before opening. Never sign in or pay after scanning a code "
             "from an unexpected email."),
        ],
        "questions": [
            ("Why are QR codes in emails risky?", ["They hide the destination URL", "They are always malware"], 0,
             "The destination is hidden until scanned."),
            ("After scanning, a login page appears unexpectedly. You…", ["Sign in", "Close it and report"], 1,
             "Unexpected login prompts after scanning are a red flag."),
        ],
    },
]

DEPARTMENTS = ["Finance", "Engineering", "Human Resources", "Sales", "Operations", "IT"]
