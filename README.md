# PhishGuard — Security-Awareness Training Platform (College OJT project)

PhishGuard is a **defensive**, multi-tenant, SaaS-style platform that helps organisations train staff to
**recognise** phishing. It has simulated lures, microlearning, quizzes, a report-phish workflow, a
defensive email analyzer, risk scoring, analytics and compliance reports.

> **It is not an attack tool.** No email is ever sent. There is no SMTP library. All "delivery" is an
> in-app preview. Every learner is synthetic, and every lure uses a fictional brand, is watermarked
> `SIMULATION — TRAINING ONLY` and comes with annotated red flags. Automated tests fail if any of
> these rules is broken. See [docs/SAFETY.md](docs/SAFETY.md).

| | |
|---|---|
| Backend | FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · LangGraph · ChromaDB |
| Frontend | Next.js 16 (App Router) · React 19 · TypeScript · Tailwind 4 · TanStack Query · Recharts |
| Database | **SQLite by default on this machine** (zero setup). PostgreSQL via `DATABASE_URL` / docker-compose |
| AI | Provider interface (OpenAI / Anthropic / any OpenAI-compatible API, e.g. **Google Gemini**, which was verified live). **DEMO MODE** with labelled, deterministic output when no key is set |

---

## Quickstart (Windows PowerShell)

These commands were run and verified on Windows 11 with Python 3.14.3 and Node 24.14.
Run them from the repository root, `C:\Users\oindr\Desktop\OJT phising`.

### One-command setup and start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # venv, deps, .env, migrate, seed, npm install
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1     # opens backend (:8001) + frontend (:3000) windows
```

Then open **http://localhost:3000** and sign in. All demo accounts are synthetic and use the
password `PhishGuard!2026` (development only):

| Role | Email |
|---|---|
| Super admin | `superadmin@globex.example.com` |
| Org admin | `admin@globex.example.com` (second tenant: `admin@initech.example.com`) |
| Manager | `manager@globex.example.com` |
| Learner | `learner@globex.example.com`, `learner2@globex.example.com` |

API docs (OpenAPI/Swagger): **http://127.0.0.1:8001/docs**

> **Why port 8001?** On the development machine another program already used port 8000, so the
> whole project defaults to 8001. Use `scripts\dev.ps1 -BackendPort 8000` if 8000 is free for you.

### Step by step (the same thing the scripts do)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt
copy ..\.env.example .env              # then set JWT_SECRET to a long random value
alembic upgrade head
python -m app.seed                     # idempotent; use --reset to rebuild
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001

# Frontend (new terminal)
cd frontend
npm install
npm run dev                            # proxies /api/v1 -> http://127.0.0.1:8001 (override with $env:BACKEND_URL)
```

### Tests, lint and evaluation

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1          # ruff, mypy, pytest, eslint, tsc, vitest
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 -E2E     # + Playwright (needs dev.ps1 running)
powershell -ExecutionPolicy Bypass -File scripts\eval.ps1          # writes eval\results\*.json
```

### Docker (PostgreSQL)

```powershell
copy .env.example .env      # set JWT_SECRET (and optionally AI keys)
docker compose up --build   # postgres + backend + frontend; add  --profile redis  for Redis
```

> The compose file and Dockerfiles are written and reviewed but **were not executed on the
> development machine**, because the Docker daemon was not running. CI builds both images.

---

## Switching to PostgreSQL

1. Start PostgreSQL 14+ and create a database, or run `docker compose up postgres`.
2. In `backend\.env`, set
   `DATABASE_URL=postgresql+psycopg://phishguard:<password>@localhost:5432/phishguard`.
3. Run `alembic upgrade head`, then `python -m app.seed`.

The models, migration and queries are dialect-neutral. Analytics uses `strftime` on SQLite and
`to_char` on PostgreSQL. **Only SQLite was exercised end-to-end in this build.**

## Adding a real AI provider

Set one provider in `backend\.env` (never commit this file). Pick one of these options:

**Google Gemini (free tier; this is the configuration that was tested live).** Gemini exposes an
OpenAI-compatible API, so it uses the `openai` provider with a different base URL. Get a key at
https://aistudio.google.com/apikey.

```
AI_PROVIDER=openai
OPENAI_API_KEY=<your Gemini key>
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
OPENAI_MODEL=gemini-3.5-flash-lite
```

**OpenAI:** `AI_PROVIDER=openai`, `OPENAI_API_KEY=sk-...`, `OPENAI_BASE_URL=https://api.openai.com/v1`.
**Anthropic:** `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=sk-ant-...`.

Restart the backend, because `.env` is read only at startup. `http://127.0.0.1:8001/health/ready` then
reports `demo_mode: false`, the DEMO MODE badge disappears, and every LLM call is prefixed with the
guardrail system prompt (see `backend/app/ai/prompts.py`). If a live call fails (bad key, rate limit,
overloaded model), the agent retries once and then falls back to the deterministic answer, so check the
backend log if answers still look like demo output.

> Gemini model names change often. If you get "model not found / no longer available", list the models
> your key can use with `GET https://generativelanguage.googleapis.com/v1beta/openai/models` and pick a
> current `flash` or `flash-lite` model. Larger models sometimes return 503 "high demand" on the free tier.

---

## Why this stack

- **FastAPI + Pydantic v2:** typed request validation, automatic OpenAPI docs and fast async I/O for SSE streaming.
- **PostgreSQL, with SQLite as the zero-setup default:** the data is relational (orgs → departments →
  people → events). It needs FK integrity, ACID and strong aggregates (GROUP BY, percentiles), so
  MongoDB isn't needed. See VIVA_GUIDE §2.
- **SQLAlchemy 2 + Alembic:** one model layer for both databases, plus versioned migrations.
- **LangGraph:** explicit agent graph (router → agent → validator) with shared state, retries and a
  checkpointer for session memory. This is easier to explain and test than free-form agent loops.
- **ChromaDB:** embedded vector store with no extra server, persisted to disk.
- **Next.js App Router + TanStack Query:** file-based routing. React Query owns all server state
  (caching, retries, invalidation). The Next.js rewrite proxy makes auth cookies first-party.
- **Tailwind + Recharts:** fast, consistent UI and charts, each with an accessible table alternative.

## Feature status (honest)

**FULLY WORKING** means implemented and covered by automated tests or verified by running it.
**DEMO-ONLY** means it works with deterministic stand-ins in place of a real external service.

| Area | Feature | Status |
|---|---|---|
| Auth | JWT access + refresh (rotation, reuse detection, revocation list), httpOnly cookies, CSRF double-submit | FULLY WORKING (tested) |
| Auth | Password policy, account lockout, TOTP 2FA, in-app invite codes | FULLY WORKING (tested) |
| Auth | SSO / OIDC | DEMO-ONLY (mock IdP; real IdP documented, not implemented) |
| Core | RBAC (4 roles) + tenant isolation (repository layer) | FULLY WORKING (RBAC matrix + cross-tenant tests) |
| Core | Audit log on every mutation, pagination/filter/sort/search, soft delete, error envelope, health/readiness, OpenAPI | FULLY WORKING (tested) |
| Campaigns | CRUD, lifecycle draft→scheduled→active→completed, department targeting, difficulty tiers, synthetic scheduler; people linked to a real login only receive the lure, and their own inbox actions are recorded as real activity | FULLY WORKING (tested) |
| Preview | Sandboxed iframe (no scripts) + CSP, watermark, red-flag hover highlight, inspect-link (displayed vs real) | FULLY WORKING (unit + E2E in Edge) |
| Analytics | Click/report/completion rates, report-to-click, time-to-report, heatmap, trends, top flags, cohorts; "Real users only" filter and a live-activity feed (auto-refresh) | FULLY WORKING (tested) |
| Exports | Analytics CSV/PDF, risk CSV, audit CSV, certificate PDF | FULLY WORKING (tested) |
| Learning | Modules, lessons, quizzes with pass mark, auto-enrolment on simulated click, progress, certificates | FULLY WORKING (tested) |
| Learning | Badges, streaks, leaderboard (department default, individual opt-in) | FULLY WORKING (tested) |
| Risk | Explainable per-person and per-department scores, weekly history | FULLY WORKING (tested) |
| Report-phish | Learner submit → "report received" notification → background heuristic triage → manager queue → in-app feedback | FULLY WORKING (tested) |
| AI | LangGraph router, 4 agents, retry-once/error node, validator node, session memory, SSE | FULLY WORKING (tested in DEMO MODE; verified live with Gemini) |
| AI | Indicator Analyst rule-based checks (SPF/DKIM/DMARC, Reply-To, link mismatch, lookalike/homoglyph, urgency…) | FULLY WORKING (tested; eval F1 0.948) |
| AI | Live LLM explanations / tips / RAG answers / example generation | VERIFIED LIVE with Google Gemini (`gemini-3.5-flash-lite`) via the OpenAI-compatible API; OpenAI and Anthropic endpoints not run |
| AI | RAG over ChromaDB with sources and "not in knowledge base" | FULLY WORKING (retrieval-only in demo; LLM answers in live mode) |
| Admin | Users, invites, API keys (hashed, scoped), webhooks (HMAC, retry/backoff, delivery log), audit viewer/export, settings, notifications | FULLY WORKING (tested) |
| Platform | JSON logs + request IDs, Prometheus `/metrics`, security headers/CSP, rate limits, gzip, caching with invalidation | FULLY WORKING |
| Platform | Redis cache/queue | NOT DONE (feature flag + compose profile only; in-process cache is used) |
| Platform | i18n | SCAFFOLD (dictionary + example partial Hindi locale; UI strings are mostly inline English) |
| DevOps | Dockerfiles, docker-compose, GitHub Actions | WRITTEN, NOT EXECUTED locally (Docker daemon off; CI not yet run) |
| Eval | Analyst (heuristic, LLM-only, combined), RAG, guardrail/validator | RUN LIVE (Gemini); RAGAS SKIPPED (`ragas` not installed) |

## Verified results (this machine)

- **Backend:** `pytest` gives 135 passed, 88% line coverage. `ruff` is clean. `mypy` is clean in lenient mode.
- **Frontend:** `eslint` and `tsc` are clean. `vitest` gives 15 passed. Playwright gives 4/4 passed in Microsoft Edge. `next build` succeeds.
- **Audits:** `npm audit --omit=dev` finds 0 vulnerabilities. `pip-audit` finds 5 chromadb advisories, which are server-mode only, documented and ignored.
- **Eval (live, Gemini `gemini-3.5-flash-lite`):** see [eval/README.md](eval/README.md).
  - **Heuristic analyzer:** accuracy 0.942, precision 0.901, recall 1.000, F1 0.948 (120 synthetic emails).
  - **LLM-only and combined:** accuracy 1.000, F1 1.000 on the same 120 synthetic emails (p50 3.2 s per call).
    The synthetic set is easy for an LLM, so treat this as a sanity check, not a real-world accuracy.
  - **RAG:** hit@1 0.958 over 24 questions; 5 of 5 out-of-scope questions declined.
  - **Validator:** 55/55. The required refusal works in live mode too.

## Known limitations

- **Only Gemini was tested live.** The OpenAI and Anthropic endpoints share the same code but were not run.
  RAGAS was not run. The free Gemini tier sometimes returns 429/503; agents retry once, then fall back to
  the deterministic answer.
- **The guardrail in live mode is a system prompt only** (by project decision). Prompt-only guardrails can be
  bypassed by determined users. Deterministic checks apply only to generated training examples (validator)
  and templates. See SAFETY.md.
- **RAG uses a lexical hashing embedder** (offline, no downloads). It is weaker than neural embeddings:
  one off-topic eval question still scores above the "not in KB" threshold (the live LLM then declines it),
  and "Which attachments are risky?" retrieves the wrong article first.
- **Rate limiting, cache, LangGraph session memory and the scheduler are in-process,** so they're single-instance only.
- **Not executed:** PostgreSQL, Docker and CI. They are configured, but only SQLite was run.
- **Type checking is lenient:** mypy suppresses ~59 Optional-narrowing warnings.
- **Dev-only npm advisories:** 5 remain in `eslint-config-next` → `braces`.

See [docs/PRODUCTION_ROADMAP.md](docs/PRODUCTION_ROADMAP.md) for the full gap list.

## Repository layout

```
backend/   FastAPI app (app/api, core, db, schemas, services, ai, workers), alembic/, tests/
frontend/  Next.js app (app/, components/, lib/, hooks/), tests/ (vitest), e2e/ (Playwright)
docs/      ARCHITECTURE, API, SAFETY, THREAT_MODEL, PRODUCTION_ROADMAP, DEPLOYMENT, VIVA_GUIDE
eval/      synthetic dataset + evaluation scripts + results/
scripts/   setup.ps1, dev.ps1, test.ps1, eval.ps1
```
