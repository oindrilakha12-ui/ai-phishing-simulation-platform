# Architecture

## 1. System overview

```mermaid
flowchart LR
  subgraph Browser
    UI["Next.js app (React, TanStack Query)"]
    IF["Sandboxed iframe (srcdoc, no scripts)"]
  end
  subgraph Frontend["Next.js server :3000"]
    RW["Rewrite proxy /api/v1/* and /health/*"]
  end
  subgraph Backend["FastAPI :8001"]
    MW["Middleware: request ID, JSON logs, metrics, body-size limit, security headers, gzip, CORS"]
    DEPS["Deps: auth (cookie+CSRF / bearer / API key), RBAC, TenantRepo"]
    R["Routers: auth, people, templates, campaigns+inbox, analytics+risk, training, reports, ai, admin, health"]
    S["Services: safety, simulation, analytics, risk, training, exports, audit, notify"]
    AI["LangGraph graph: router, analyst, coach, qa, generator, validator, refuse, error"]
    WK["BackgroundTasks: synthetic launch, report triage, webhook delivery"]
  end
  DB[("SQLite (default) / PostgreSQL")]
  VS[("ChromaDB (embedded, persistent)")]
  LLM["LLM provider (optional): OpenAI / Anthropic"]
  HOOK["Registered webhook endpoints (JSON, HMAC)"]

  UI -->|fetch, cookies| RW --> MW --> DEPS --> R --> S --> DB
  R --> AI --> VS
  AI -. only if key set .-> LLM
  R --> WK --> HOOK
  UI --- IF
```

Key decisions:

- **One origin for the browser.** The Next.js server proxies `/api/v1/*` to FastAPI. Auth cookies are
  first-party (`SameSite=Lax`, `HttpOnly`), and the backend CORS allow-list is only a fallback.
- **No outbound email path exists.** The only outbound HTTP is (a) webhooks to URLs an admin registered
  and (b) the optional LLM provider.
- **Tenant isolation lives in one place:** `app/db/repository.py`. `TenantRepo` adds
  `WHERE org_id = :org AND deleted_at IS NULL` to every query and refuses to let callers choose `org_id`.

## 2. Request lifecycle (cookie session)

1. The browser sends a request with the `pg_access` cookie. For POST/PATCH/DELETE it also sends the
   `X-CSRF-Token` header, copied from the readable `pg_csrf` cookie.
2. Middleware assigns a request ID, checks body size, and later adds security headers and Prometheus metrics.
3. `get_principal` validates the JWT and checks the `jti` against the revocation list. For cookie auth
   on unsafe methods, it compares the CSRF header to the cookie (constant time).
4. `require_role(min_role, api_scope)` enforces RBAC. API keys pass only on GET endpoints that declare a matching scope.
5. The handler uses `TenantRepo` for every read and write, then calls `audit_p(...)` for mutations
   (who / what / when / IP / request ID).
6. Errors are rendered by `install_error_handlers` as `{"error": {code, message, details}, "request_id"}`.

### JWT flow

```mermaid
sequenceDiagram
  participant B as Browser
  participant A as API
  B->>A: POST /auth/login (email, password, [totp])
  A-->>B: Set-Cookie pg_access (15 min), pg_refresh (7 d, path=/api/v1/auth), pg_csrf
  B->>A: GET /campaigns (cookie)
  A-->>B: 200
  Note over B,A: access token expires
  B->>A: GET /campaigns
  A-->>B: 401 token_expired
  B->>A: POST /auth/refresh (refresh cookie + CSRF header)
  A->>A: revoke old refresh, issue new one in same family
  A-->>B: new cookies, then the client retries the original call
  Note over A: re-use of a revoked refresh token revokes the whole family
```

## 3. LangGraph multi-agent graph

```mermaid
flowchart TD
  START((start)) --> router
  router -->|analyze| analyst
  router -->|coach| coach
  router -->|qa| qa
  router -->|generate_example| generator
  router -->|out_of_scope| refuse
  analyst -->|error and attempts lt 2| analyst
  coach -->|error and attempts lt 2| coach
  qa -->|error and attempts lt 2| qa
  generator -->|error and attempts lt 2| generator
  analyst -->|error twice| error_node
  coach -->|error twice| error_node
  qa -->|error twice| error_node
  generator -->|error twice| error_node
  generator -->|ok| validator
  analyst -->|ok| finish
  coach -->|ok| finish
  qa -->|ok| finish
  validator --> finish
  refuse --> finish
  error_node --> finish
  finish --> END((end))
```

- **Shared state:** `org_id, user_id, session_id, messages[], demo_mode` plus per-turn working fields
  (`request_type, input, result, error, attempts, usage`).
- **Session memory:** a `MemorySaver` checkpointer keyed by `org_id:user_id:session_id`, so one tenant's
  session can never be read by another. `messages` uses an additive reducer.
- **Guardrail:** every live LLM call goes through `providers.py`, which always prepends `GUARDRAIL_PREFIX`.
  In demo mode the router accepts only the four in-scope request types, and everything else is refused
  with a defensive alternative.
- **Validator node:** checks generated examples for the watermark, an approved fictional brand, red flags
  and subject/body. A failing output is replaced with a known-safe default.
- **Streaming:** `/api/v1/ai/stream` runs the graph and then streams the final text over SSE
  (`meta → token* → result → done`). A live provider could stream tokens directly. This build streams
  the finished output in chunks, which is honest and simple.

| Agent | Live mode | Demo mode |
|---|---|---|
| Indicator Analyst | Rule-based checks, then LLM explains each indicator | Rule-based checks + canned explanation labelled `DEMO — example explanation` |
| Awareness Coach | LLM writes 3 tips from synthetic history | 3 tips from a 12-entry library, weakest category first |
| Knowledge Q&A | Retrieve → LLM answers from `<document>` excerpts only, cites sources | Top retrieved chunk returned verbatim (retrieval-only) |
| Training Example Generator | LLM JSON → validator | One of 5 pre-written fictional examples → validator |

## 4. RAG pipeline

1. Seven original awareness notes live in `backend/app/ai/knowledge/*.md`. They are also stored as `KnowledgeDoc` rows per org.
2. Chunking splits on paragraphs and packs them up to about 700 characters.
3. Embedding uses a deterministic hashing embedder (word unigrams + bigrams, light stemming, 512 dims,
   L2-normalised). It needs no download and no key. The trade-off is lexical, not semantic, matching.
4. The vector store is ChromaDB `PersistentClient` with cosine distance, falling back to an in-memory store.
5. If the top similarity is below `MIN_SIMILARITY = 0.18`, the answer is exactly `not in knowledge base`.
6. **Prompt-injection hardening:** retrieved text is wrapped in `<document>` tags, and the system prompt
   says the excerpts are data, not instructions. In demo mode no LLM reads the text at all.

## 5. Data model (ER)

Every business table carries `org_id` (indexed FK to `organizations`) and `deleted_at` (soft delete).

```mermaid
erDiagram
  ORGANIZATION ||--o{ USER : has
  ORGANIZATION ||--o{ DEPARTMENT : has
  DEPARTMENT ||--o{ TARGET : contains
  USER |o--o| TARGET : "learner profile"
  ORGANIZATION ||--o{ TEMPLATE : owns
  TEMPLATE ||--o{ TEMPLATE_VERSION : history
  CAMPAIGN }o--|| TEMPLATE : uses
  CAMPAIGN }o--o{ DEPARTMENT : targets
  CAMPAIGN ||--o{ SIMULATION_EVENT : produces
  TARGET ||--o{ SIMULATION_EVENT : experiences
  TRAINING_MODULE ||--o{ LESSON : has
  TRAINING_MODULE ||--|| QUIZ : has
  QUIZ ||--o{ QUIZ_QUESTION : has
  QUIZ ||--o{ QUIZ_ATTEMPT : records
  TARGET ||--o{ ENROLLMENT : has
  TRAINING_MODULE ||--o{ ENROLLMENT : in
  TARGET ||--o{ CERTIFICATE : earns
  USER ||--o{ REPORTED_EMAIL : submits
  ORGANIZATION ||--o{ RISK_SCORE : history
  ORGANIZATION ||--o{ AUDIT_LOG : records
  ORGANIZATION ||--o{ API_KEY : issues
  ORGANIZATION ||--o{ WEBHOOK : registers
  WEBHOOK ||--o{ WEBHOOK_DELIVERY : logs
  ORGANIZATION ||--o{ KNOWLEDGE_DOC : stores
  USER ||--o{ NOTIFICATION : receives
  USER ||--o{ REFRESH_TOKEN : holds
  ORGANIZATION ||--o{ INVITE : creates
```

Indexes cover every FK and filter column, plus composite indexes for the hot analytics paths:
`(org_id, event_type, occurred_at)` and `(campaign_id, target_id)` on events,
`(org_id, created_at)` on the audit log, and `(org_id, scope, subject_id, computed_at)` on risk scores.

## 6. Performance

- **N+1 avoidance:** campaign list stats come from one grouped query (`campaign_stats`). Relationships use
  `joined`/`selectin` loading.
- **Caching:** analytics overview and risk scores are cached per org (TTL 120 s). Every write that changes
  events, campaigns, enrollments or reports calls `cache.invalidate_org(org_id)`.
- **Compression:** GZip middleware for responses over 1 KB.

## 7. SSO readiness

`app/services/oidc.py` defines `OIDCProvider` (`authorization_url`, `exchange_code`). Only
`MockOIDCProvider` is implemented. Its "authorize" step returns a one-time code for a chosen email, and
`/auth/oidc/{provider}/callback` links it to an **existing** active user (no auto-provisioning).

A real IdP (Entra ID, Okta, Google) would implement the same interface:
1. Authorization-code + PKCE.
2. Verify the ID token signature against the IdP JWKS.
3. Check `iss`, `aud`, `nonce` and expiry.
4. Map `email`/`sub` to a user.

SCIM provisioning is not implemented.

## 8. Observability

- **Logs:** structured JSON to stdout (`app/core/logging.py`), with `request_id` on every line. Clients
  can pass `X-Request-ID`, and it is echoed back.
- **Metrics:** `/metrics` (Prometheus) exposes `phishguard_http_requests_total{method,route,status}` and
  `phishguard_http_request_seconds`. Scrape the backend directly; the frontend does not proxy `/metrics`.
- **Tracing hook:** `span()` context manager. Swap it for OpenTelemetry in production.
- **Frontend:** a React error boundary wraps each page, and a toast system shows API errors with their request IDs.
