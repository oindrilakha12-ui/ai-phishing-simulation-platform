# Threat model

## Assets

- Tenant data: users, synthetic people, campaign outcomes, reports, audit logs
- Credentials and secrets: password hashes, TOTP secrets, JWT signing key, API keys, webhook secrets, LLM keys
- The platform's reputation: it must never become a phishing tool

## Trust boundaries

Browser ⇄ Next.js proxy ⇄ FastAPI ⇄ database / ChromaDB. FastAPI → registered webhook URLs.
FastAPI → LLM provider (optional). Pasted email content, retrieved knowledge text and LLM output
are all treated as **untrusted data**.

## STRIDE

| Threat | Example | Mitigation (where) |
|---|---|---|
| **S**poofing | Stolen password; forged JWT; stolen refresh token | bcrypt (cost 12), password policy, lockout after 5 failures (`routes/auth.py`); optional TOTP 2FA; HS256 JWT with ≥32-char secret, production refuses the dev secret (`core/config.py`); refresh rotation with family revocation on reuse (`services/auth_service.py`); timing-equalised login for unknown emails |
| **T**ampering | CSRF on cookie session; mass-assignment of `org_id`; template HTML injection | Double-submit CSRF token for cookie auth (`api/deps.py`); `TenantRepo.add` drops caller-supplied `org_id`; Pydantic schemas with explicit fields; HTML allow-list sanitizer + sandboxed iframe + CSP (`services/safety.py`) |
| **R**epudiation | "I didn't change that campaign" | Audit log on every mutation with actor, action, entity, IP, request ID and timestamp; CSV export (`services/audit.py`, `routes/admin.py`) |
| **I**nformation disclosure | Cross-tenant reads; IDOR; verbose errors; secrets in logs | Repository-layer tenant filter + identical 404 for "not yours" (`db/repository.py`, isolation tests); generic 500 envelope; API keys and invite codes stored as SHA-256; secrets shown once; no request bodies logged |
| **D**enial of service | Login brute force; AI endpoint abuse; huge payloads | Rate limits on auth, AI and report-phish (`core/ratelimit.py`); 256 KB body cap (middleware); Pydantic size limits; page_size ≤ 200 |
| **E**levation of privilege | Learner calls admin API; admin grants super_admin; API key writes | `require_role` RBAC with tested matrix; admins can't assign above their own role or modify higher roles; API keys are read-only and scope-checked |

## Specific risks

| Risk | Mitigation |
|---|---|
| Platform abused to phish real people | No mail transport; fictional-brand allow-list; reserved domains only; watermark; no export-to-send; synthetic people only; no contact import |
| Prompt injection via pasted email or KB text | Email wrapped in `<email>` and KB text in `<document>` tags, declared "data, not instructions"; demo mode has no LLM; LLM output is post-processed (JSON parse, length caps); generator output passes the validator |
| SSRF via webhooks | http/https only; production requires https and blocks private/loopback/link-local/reserved IPs; no redirects followed; 5 s timeout (`workers/webhooks.py`) |
| CSV/formula injection in exports | Cells starting with `= + - @` are prefixed with `'` (`services/exports.py`) |
| XSS | React escapes by default; lesson Markdown renderer builds React nodes (no `dangerouslySetInnerHTML`); app CSP; email previews only in a script-less sandboxed iframe |
| Clickjacking | `X-Frame-Options: DENY` and `frame-ancestors 'none'` on both servers |
| Open redirect after login | `next` parameter must start with a single `/` |

## Accepted risks (documented)

- **chromadb 1.5.9 advisories** (PYSEC-2026-311, -3813, -3814, -3815) affect the Chroma **HTTP server**
  (REST API, RBAC provider, `trust_remote_code` embedding functions). PhishGuard uses Chroma
  **embedded in-process** with precomputed embeddings and exposes no Chroma server, so these code paths
  are not reachable. No fixed version exists. They are ignored in CI with a comment; re-evaluate on upgrade.
- **Dev-only npm advisories** in `eslint-config-next` → `braces` (lint tooling, not shipped).
- **In-process rate limiter, cache and session memory:** acceptable for a single instance only.

# OWASP Top 10 (2021) mapping

| OWASP risk | Where it is mitigated |
|---|---|
| A01 Broken Access Control | `api/deps.py` (`require_role`, API-key scopes), `db/repository.py` (tenant filter, soft delete), admin role-escalation guards; tests: `test_rbac_and_tenancy.py` |
| A02 Cryptographic Failures | bcrypt passwords; SHA-256 hashed API keys/invite codes; HMAC-SHA256 webhook signatures; `Secure` cookies + HSTS when `COOKIE_SECURE=true`; production secret checks |
| A03 Injection | SQLAlchemy parameterised queries; sort columns allow-listed (`invalid_sort`); HTML sanitizer; CSV formula neutralisation; prompt-injection delimiting |
| A04 Insecure Design | Safety scope designed out (no mail, no inputs on landing pages, synthetic data); threat model; validator node |
| A05 Security Misconfiguration | Security headers + CSP on both servers; CORS locked to frontend origin; docs disabled from CSP only for Swagger; production-mode startup checks; non-root containers |
| A06 Vulnerable Components | Pinned dependencies; `pip-audit`, `npm audit`, SBOM and gitleaks in CI; accepted-risk register above |
| A07 Identification & Auth Failures | Lockout, password policy, TOTP, refresh rotation + reuse detection, access-token revocation on logout, session kill on deactivation |
| A08 Software & Data Integrity Failures | Signed JWTs; HMAC-signed webhooks with timestamp; template version history; CI pipeline |
| A09 Logging & Monitoring Failures | Structured JSON logs with request IDs; audit log with IP; Prometheus metrics; failed logins and lockouts audited |
| A10 SSRF | Webhook URL validation (scheme, private-IP block in production, no redirects, timeout) |
