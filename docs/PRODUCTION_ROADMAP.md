# Production roadmap: an honest gap list

PhishGuard is a working college-OJT build. Everything below is **design only, NOT implemented**,
unless it says otherwise. It is the gap between this build and a product an organisation could run.

## 1. Legal and authorization

- **Written authorization workflow** before any simulation can target real staff. That means sign-off
  from the client's leadership, HR, legal and works council where applicable, a recorded scope, an
  approval audit trail, and expiry.
- **Data Processing Agreement (DPA)** and a privacy review (GDPR / India's DPDP Act 2023): lawful basis,
  data minimisation, retention schedule, data-subject rights (access/erasure), and a DPIA.
- **Ethics policy:** no punitive use of results, aggregated reporting by default, an opt-out process, and
  a rule against lures that exploit sensitive topics (health, bereavement, layoffs).

## 2. Real delivery (deliberately absent today)

Real email delivery is out of scope for this project, and its absence is enforced by tests. A
production product that chose to add it would need:

- **Domain verification:** SPF/DKIM/DMARC records and DNS TXT proof of control of the client domain.
- **Allow-listing** with the client's mail gateway (Microsoft 365 / Google Workspace phishing-simulation
  allow-lists) so simulations don't poison real filters.
- **Recipient allow-list** sourced only from a verified directory sync. No free-form address entry.
- **Dedicated sending infrastructure** with rate limits, bounce handling and suppression lists.
- **Kill switch,** plus per-campaign approval and send windows.

## 3. Identity

- **Real OIDC/SAML IdPs** (Entra ID, Okta, Google Workspace) implementing the existing `OIDCProvider`
  interface: authorization-code + PKCE, JWKS signature validation, and `nonce`/`aud`/`iss` checks.
- **SCIM 2.0** user/group provisioning and de-provisioning.
- **Passkeys/WebAuthn** as phishing-resistant MFA. Encrypt TOTP secrets at rest (envelope encryption / KMS).
- Admin step-up authentication for sensitive actions.

## 4. Security assurance

- An independent **penetration test** and remediation cycle.
- **SOC 2 Type II controls:** change management, access reviews, vendor management, incident response
  runbooks, evidence collection.
- A moderation classifier on LLM input and output, in addition to the system-prompt guardrail
  (see SAFETY.md, limitations).
- WAF / bot protection in front of the app. Distributed rate limiting (Redis).
- Secrets in a managed vault (Azure Key Vault / AWS Secrets Manager), with JWT key rotation (kid + JWKS).
- Strict CSP with nonces instead of `'unsafe-inline'` for scripts.

## 5. Scale and reliability

- **PostgreSQL in production:** managed instance with HA, PITR backups and tested restores; connection
  pooling (PgBouncer); read replicas for analytics.
- **Multi-instance safe state:** move the rate limiter, cache, LangGraph checkpointer (Postgres/Redis
  saver), and the scheduler/background jobs (Celery/RQ/Arq workers, or a durable queue) out of process.
- **Analytics at scale:** pre-aggregated tables or materialised views refreshed incrementally; partition
  `simulation_events` by month.
- **Row-Level Security** in PostgreSQL as defence-in-depth behind the repository-layer tenant filter.
- Zero-downtime migrations, blue/green deploys, autoscaling, CDN for static assets.

## 6. Backups and DR

- Automated daily backups plus WAL archiving, cross-region copies, quarterly restore drills, and
  documented RPO/RTO targets.
- Backup and versioning of the vector store, or rebuilding it from `knowledge_docs`.

## 7. Observability

- OpenTelemetry tracing (replacing the `span()` hook), centralised logs (Loki/ELK), alerting
  (Prometheus Alertmanager) and SLOs.
- Frontend error reporting (Sentry or similar) with PII scrubbing.

## 8. Product and AI

- Neural embeddings (e.g. a sentence-transformer or provider embeddings) instead of the lexical hashing
  embedder; RAGAS in CI against a live judge.
- Token-by-token streaming from the provider instead of chunking the final output.
- Full i18n (next-intl), plus translated training content and KB.
- WCAG 2.2 AA audit with assistive-technology users. Automated axe checks are not yet in CI.
- Stricter typing (remove mypy's disabled error codes; ~59 Optional-narrowing warnings).

## 9. Not executed in this build

- **Docker compose and the Dockerfiles** were not run (the Docker daemon was off on the dev machine).
- **The GitHub Actions workflow** has not run yet (the repo was not pushed).
- **PostgreSQL** was not exercised end-to-end (SQLite only).
- **Live LLM providers** were not called (no API key).
- **The deployment guides** in DEPLOYMENT.md are untested.
