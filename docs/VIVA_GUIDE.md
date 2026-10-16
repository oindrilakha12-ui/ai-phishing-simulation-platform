# Viva guide

A study guide for presenting and defending PhishGuard. Each section explains a concept, then shows
where it lives in the code so you can open the file during the viva.

---

## 1. The one-minute pitch

PhishGuard is a multi-tenant training platform that teaches employees to **recognise** phishing.
Managers run *campaigns*. A campaign shows a fictional, watermarked lure to synthetic learners
**inside the app**, and nothing is ever emailed. Every lure has annotated red flags. Outcomes
(previewed, clicked, reported) feed analytics and an explainable risk score. Learners who "click" are
auto-enrolled in a matching micro-course with a quiz and certificate. Learners can report suspicious
email, and a defensive analyzer pre-triages it. An AI Studio adds four LangGraph agents (analyzer,
coach, knowledge Q&A with RAG, training-example generator), all safe in a labelled demo mode.

**Architecture in one sentence:** a Next.js frontend proxies to a FastAPI backend. The backend enforces
auth, RBAC and tenant isolation, stores data in SQLite/PostgreSQL through SQLAlchemy, and runs AI
through a LangGraph graph with a ChromaDB knowledge base.

## 2. Why PostgreSQL (and not MongoDB)?

- **The data is relational.** Organization → departments → people → events; campaigns ↔ departments
  (many-to-many); modules → lessons → quiz → questions. Foreign keys keep it consistent: you cannot have
  an event for a person who doesn't exist.
- **Analytics need SQL.** Click rate per department per month is `GROUP BY department, month` with
  `COUNT(DISTINCT …)`. PostgreSQL does this efficiently with indexes. Doing it in MongoDB needs
  aggregation pipelines and gives no FK guarantees.
- **ACID transactions.** A quiz pass updates the enrollment, creates a certificate and logs an event
  *atomically*. Either all happen or none do.
- **Schema evolution** is handled by Alembic migrations (versioned, reviewable).
- **SQLite is the default** only because it needs zero setup for a demo. The same models and migrations
  run on PostgreSQL by changing `DATABASE_URL`.
- MongoDB would suit unstructured, schema-less documents at massive horizontal scale. That isn't our problem.

## 3. DBMS concepts you can point to

| Concept | Where |
|---|---|
| Primary keys (UUID hex), foreign keys with `ON DELETE CASCADE` | `app/db/models.py` |
| Many-to-many join table | `campaign_departments` |
| Unique constraints | `uq_department_org_name`, `uq_enrollment_target_module`, `users.email` |
| Indexes (single + composite) | `ix_events_org_type_time (org_id, event_type, occurred_at)` speeds the analytics filters |
| Normalisation | Departments, templates and modules are separate tables referenced by ID (3NF). JSON is used only for naturally nested data (red flags, quiz options, audit details) |
| Soft delete | `deleted_at` column; every read filters `deleted_at IS NULL` |
| Transactions | One SQLAlchemy session per request, with `commit()` at the end of the handler |
| Migrations | `alembic/versions/0001_initial_schema.py` |
| Avoiding N+1 queries | `campaign_stats()` computes all campaigns' KPIs in one `GROUP BY` |
| Aggregates | `COUNT(DISTINCT campaign_id || ':' || target_id)` per event type in `services/analytics.py` |

## 4. DSA concepts you can point to

| Concept | Where | Complexity |
|---|---|---|
| **Levenshtein edit distance** (dynamic programming) to catch look-alike domains like `paypa1.com` | `app/ai/heuristics.py: levenshtein` | O(m·n) time, O(n) memory (two rows) |
| **Homoglyph normalisation** (translation table: `0→o`, `1→l`, `rn→m`, Cyrillic look-alikes) | `skeleton()` | O(n) |
| **Sliding-window rate limiter** (deque of timestamps per key) | `app/core/ratelimit.py` | amortised O(1) per request |
| **TTL cache** (hash map with expiry) and prefix invalidation | `app/core/cache.py` | O(1) get/set |
| **Percentiles** (sort + linear interpolation) for time-to-report p50/p90 | `services/analytics.py: _percentile` | O(n log n) |
| **Cosine similarity / vector search** | `app/ai/rag.py` | Chroma uses HNSW (approximate nearest neighbour graph) |
| **Feature hashing** (the hashing trick) for embeddings | `rag.embed` | O(tokens) |
| **State machine** for the campaign lifecycle | `TRANSITIONS` dict in `routes/campaigns.py` | O(1) check |
| **Graph** (directed, with conditional edges) for agents | `app/ai/graph.py` | |

## 5. Authentication and JWT flow

1. **Login:** the password is checked with **bcrypt** (slow, salted hash). After 5 failures the
   account locks for 15 minutes. If TOTP 2FA is enabled, a 6-digit code is also required.
2. The server issues two **JWTs** (signed with HMAC-SHA256):
   - an **access token** (15 min) holding user ID, org ID, role and a unique `jti`;
   - a **refresh token** (7 days) holding a `family` ID.
3. Both go into **httpOnly cookies**, so JavaScript cannot read them. This protects against token theft by XSS.
4. **CSRF protection:** because browsers send cookies automatically, a malicious site could trigger a
   POST. We use the *double-submit* pattern. A readable `pg_csrf` cookie must be copied into an
   `X-CSRF-Token` header. Other sites can't read our cookie, so they can't forge the header.
5. **Refresh rotation:** each refresh revokes the old refresh token and issues a new one in the same
   family. If an old token is ever reused, someone stole it, so the whole family is revoked.
6. **Logout** adds the access token's `jti` to a **revocation list**, so it stops working before expiry.

## 6. Multi-tenancy

- Every business row has `org_id`. **One class, `TenantRepo`,** builds every query and always adds
  `WHERE org_id = <current user's org> AND deleted_at IS NULL`.
- Callers can't pass `org_id`; the repository sets it.
- If you request another organisation's record by ID, you get **404**, exactly as if it didn't exist.
  This avoids leaking that it exists (no "existence oracle").
- **Proof:** `tests/test_rbac_and_tenancy.py` logs in as Globex's admin and tries to read, patch, delete
  and triage Initech's records. All attempts return 404, and the list endpoints never include the other org's rows.
- **Production hardening idea:** PostgreSQL Row-Level Security as a second layer.

## 7. RBAC

The roles are `learner < manager < org_admin < super_admin`. `require_role("manager")` is a FastAPI
dependency that returns 403 for lower roles. The RBAC test is a **matrix**: 13 endpoints × 4 roles, all
checked automatically. Admins cannot grant a role higher than their own, and nobody can assign
`super_admin` through the API.

## 8. LangGraph and the agents

- **What is LangGraph?** A library for building LLM applications as a **graph of nodes** that share a
  **state** object. Edges can be conditional, so routing, retries and validation are explicit and testable.
- **Our graph:** `router → (analyst | coach | qa | generator | refuse)`. Then:
  - generator → **validator**;
  - any failing agent is **retried once**, then goes to an **error node** with a graceful message;
  - finally, `finish` appends the turn to **session memory** (a checkpointer keyed by org, user and session).
- **Guardrail:** a fixed system prompt is prepended to every live LLM call. The router only accepts the
  four in-scope tasks; anything else is refused with a defensive alternative.
- **DEMO MODE:** with no API key, each agent returns deterministic, *labelled* output. Examples are the
  rule-based analysis with a "DEMO — example explanation", tips from a library, and the top retrieved
  passage. We never present demo output as real model output.
- **Streaming:** Server-Sent Events, a one-way HTTP stream of `event:`/`data:` lines, so the UI shows
  text as it arrives.

## 9. RAG (Retrieval-Augmented Generation)

1. **Chunk** the knowledge-base notes into about 700-character passages.
2. **Embed** each chunk as a vector. We use a local hashing embedder: deterministic and offline, but
   lexical rather than semantic.
3. **Store** the vectors in ChromaDB.
4. **At question time:** embed the question, retrieve the top 3 chunks by cosine similarity, and refuse
   with "not in knowledge base" if the best similarity is below 0.18.
5. **Generate** (live mode): give the LLM only those chunks, wrapped in `<document>` tags and marked as
   *data, not instructions* (prompt-injection hardening), and ask it to cite titles.

**Why RAG?** It grounds answers in our vetted content, reduces hallucination, lets us cite sources and
update knowledge without retraining.

## 10. Evaluation metrics

- **Confusion matrix:** TP (phish flagged), FP (legit flagged), FN (phish missed), TN (legit passed).
- **Accuracy** = (TP+TN)/N. **Precision** = TP/(TP+FP): of what we flagged, how much was really phishing.
  **Recall** = TP/(TP+FN): of all phishing, how much we caught. **F1** = harmonic mean of precision and recall.
- For a security tool, **recall matters most** (missing phishing is worse than an extra warning).
  Our heuristics: recall 1.0, precision 0.90, F1 0.948 on 120 synthetic emails.
- **Latency p50/p95:** the median and 95th-percentile response time. p95 shows the "slow tail".
- **RAG:** hit@k (correct document in the top k), MRR (mean reciprocal rank), and the out-of-scope refusal rate.
  **RAGAS** adds LLM-judged faithfulness, relevancy and context precision/recall (skipped without a key).
- **Honesty point:** the same person wrote the dataset and the rules, so the scores are optimistic.

## 11. Security and ethics

- **Ethics first:** no email sending, no credential capture, synthetic people only, fictional brands,
  watermark, red flags always shown, no "export to send". All of it is enforced by tests, not only by policy.
- **OWASP Top 10** mapping and a **STRIDE** threat model are in `docs/THREAT_MODEL.md`.
- **Defence in depth on previews:** server-side HTML sanitisation, neutralised links, an iframe
  `sandbox` without `allow-scripts`, and a CSP `default-src 'none'`.
- **Privacy:** the leaderboard is department-level by default; individuals appear only if they opt in.
- **In real life, phishing simulations need** written authorization, a privacy review, and non-punitive
  use of results (see PRODUCTION_ROADMAP §1).

---

## 12. Likely viva questions and answers

1. **Q: How do you guarantee the platform can't be used to phish real people?**
   A: There is no code path to send email. There's no mail library, and a test scans every import and
   dependency file. Lures must use an allow-listed fictional brand and reserved `.example` domains, carry
   a watermark, and include red flags, all validated on create and update. People are synthetic, and
   there's no contact import.

2. **Q: Why store JWTs in httpOnly cookies instead of localStorage?**
   A: JavaScript can't read httpOnly cookies, so an XSS bug can't steal the token. The trade-off is CSRF
   exposure, which we close with the double-submit CSRF token.

3. **Q: What happens if a refresh token is stolen?**
   A: Rotation means every use issues a new token and revokes the old one. If the attacker and the user
   both use it, the second use presents a revoked token. We detect the reuse and revoke the whole family,
   forcing a fresh login.

4. **Q: How is tenant isolation enforced, and how did you test it?**
   A: Centrally, in `TenantRepo`, which always filters by the caller's `org_id`. Tests log in as one
   tenant's admin and try every detail, list and mutation endpoint with the other tenant's IDs. All
   return 404, and the lists never leak.

5. **Q: Why return 404 instead of 403 for another tenant's record?**
   A: A 403 would confirm the record exists. A 404 gives an attacker no information.

6. **Q: Explain your risk score.**
   A: It starts at 30. It adds 50 × click rate, adds up to 16 for recent clicks, subtracts 25 × report
   rate and 15 × training completion, and adds up to 15 for unfinished assigned training. The result is
   clamped to 0–100. Each term is returned as a "factor", so the UI explains *why* someone is high-risk.
   Department risk is the average of its people's scores.

7. **Q: What is the report-to-click ratio, and why does it matter?**
   A: Reports divided by clicks. Above 1 means people report lures more often than they fall for them,
   which is the behaviour we want to build.

8. **Q: How does the email preview stay safe?**
   A: The HTML is sanitised server-side with an allow-list that drops forms, inputs, scripts and iframes.
   Links are replaced with `#`, keeping the real URL only for the "inspect link" panel. The result is
   rendered in an iframe `sandbox` with no `allow-scripts` and a strict CSP meta tag.

9. **Q: Why LangGraph instead of one big prompt?**
   A: The graph makes routing, retries, validation and refusal explicit nodes. Each node can be unit
   tested, and the flow is easy to draw and reason about.

10. **Q: What does the validator node do?**
    A: It checks generated training examples for the exact watermark, an approved fictional brand (not
    in the real-brand list, and on the allow-list), and present red flags. If anything fails, it returns a
    known-safe default example instead of the flagged output.

11. **Q: What is DEMO MODE and why is it important?**
    A: With no API key, every agent returns deterministic, clearly labelled output, and the UI shows a
    DEMO badge. It makes the app fully runnable offline, and it's honest: we never pass off demo text as
    an AI result.

12. **Q: How do you stop prompt injection in RAG?**
    A: Retrieved text and pasted emails are wrapped in tags and declared "data, not instructions". The
    knowledge base is our own vetted content. In demo mode no LLM reads it at all.

13. **Q: Precision vs recall: which matters more for phishing detection?**
    A: Usually recall, because a missed phish can cause a breach while a false alarm only costs a little
    time. Too many false alarms cause alert fatigue, though, so we report both, plus F1.

14. **Q: How do you avoid N+1 queries on the campaign list?**
    A: Instead of querying stats per campaign, `campaign_stats()` runs one grouped query for all
    campaigns on the page. Relationships use joined/select-in eager loading.

15. **Q: How is the analytics cache kept correct?**
    A: Aggregates are cached per org with a TTL. Every write that changes the underlying data (campaign
    transition, inbox action, quiz pass, report) calls `invalidate_org`, so stale numbers are never served
    after a write.

16. **Q: What would you change for production?**
    A: Real IdP + SCIM, PostgreSQL with RLS and backups, Redis-backed rate limiting/cache/queues, a
    moderation classifier alongside the system prompt, neural embeddings, a pen test, SOC 2 controls,
    and a legal authorization workflow (see PRODUCTION_ROADMAP).

17. **Q: How are webhooks secured?**
    A: Admins register URLs. Each delivery is JSON signed with HMAC-SHA256 over `timestamp.body`, so the
    receiver can verify both authenticity and freshness. URLs are validated (no private IPs in
    production, no redirects) to prevent SSRF. Failures retry with exponential backoff and are logged.

18. **Q: What is CSP and what does yours do?**
    A: Content-Security-Policy tells the browser which sources may load scripts, frames and so on. The app
    allows only its own origin and forbids being framed (`frame-ancestors 'none'`). Email previews get
    `default-src 'none'`, so nothing inside them can load or run.

19. **Q: What are the limitations of your evaluation?**
    A: The dataset is synthetic and written by the same author as the rules, LLM-only and RAGAS were
    skipped with no key, and the lexical embedder let one off-topic question through. I report these
    openly rather than tuning to the test set.

20. **Q: How does auto-enrolment work?**
    A: When a simulated click is recorded, its red-flag category is mapped to a training module category
    (link → "Links and look-alike domains"), and the person is enrolled with `source="auto"` and notified in-app.

## 13. Demo script (5 minutes)

1. Log in as **manager** and show the dashboard: KPIs, heatmap, trend, cohort comparison and the PDF export.
2. Go to **Templates**, open "Parking permit renewal" and hover the red flags. The cue highlights in the
   sandboxed preview. Show the link mismatch.
3. Go to **Campaigns**, open the draft and click **Launch now**. Synthetic events appear in the log.
4. Go to **AI Studio**. Analyze the sample email (score 100 + indicators). Generate a training example
   (validator passed). In Q&A, ask "How do I report a suspicious email?" (answer with sources). Turn on
   free-text mode and type "a fake login page for a real bank" to show the refusal.
5. Log in as **learner**. In **Inbox**, report a simulation and see "Well spotted". Take a training quiz
   and download the certificate.
6. Log in as **admin**. Show the **Audit log**, filtered by `campaign.`, with your launch action listed.
