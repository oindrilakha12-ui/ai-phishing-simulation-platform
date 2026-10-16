# API reference

The interactive OpenAPI docs are served by the backend at **http://127.0.0.1:8001/docs** (Swagger) and
`/redoc`. The machine-readable spec is at `/openapi.json`. This page summarises the conventions and lists
every endpoint. The table is generated from the live OpenAPI spec (99 operations).

## Conventions

**Base path.** All endpoints are under `/api/v1`, except `/health/*` and `/metrics`.

**Authentication.** There are three methods:

| Method | How | Notes |
|---|---|---|
| Cookie session | `POST /auth/login` sets `pg_access` (httpOnly, 15 min), `pg_refresh` (httpOnly, 7 days, path `/api/v1/auth`) and `pg_csrf` (readable) | Mutating requests **must** send `X-CSRF-Token: <pg_csrf value>` |
| Bearer token | `POST /auth/login?include_token=true` returns `access_token`; send `Authorization: Bearer …` | For scripts/tests; no CSRF needed |
| API key | `X-API-Key: pg_…` (created in Admin → API keys) | Read-only; only endpoints declaring a matching scope (`analytics:read`: `/analytics/overview`, `/risk/*` GETs) |

**Roles.** The order is `learner < manager < org_admin < super_admin`. Endpoints declare a minimum role.

**Lists.** Every list endpoint takes `page` (≥1), `page_size` (1–200), `sort` (allow-listed per
endpoint), `order` (`asc|desc`) and `q` (search), and returns `{items, total, page, page_size}`.

**Errors.** Every error uses one envelope:

```json
{"error": {"code": "not_found", "message": "Campaign not found", "details": null}, "request_id": "9f…"}
```

| Code | Meaning |
|---|---|
| `validation_error` (422) | Request validation failed |
| `unsafe_template` (422) | Lure violates the safety scope |
| `invalid_transition` (409) | Campaign lifecycle transition not allowed |
| `csrf_failed` (403) | Missing or invalid CSRF token |
| `forbidden` (403) | Not allowed for this role or scope |
| `token_expired` / `token_revoked` / `refresh_reuse` (401) | Session problems |
| `account_locked` (423) | Too many failed logins |
| `rate_limited` (429) | Too many requests |
| `payload_too_large` (413) | Request body over the size limit |

**Other conventions.**
- **Soft delete:** `DELETE` sets `deleted_at`. Deleted rows disappear from every read.
- **Tenant isolation:** another organization's IDs return **404**, the same as non-existent IDs.
- **Request IDs:** every response has `X-Request-ID`, which is also included in logs and audit entries.

## Examples

```powershell
# Log in (bearer token for scripting)
$s = Invoke-RestMethod -Method Post "http://127.0.0.1:8001/api/v1/auth/login?include_token=true" `
     -ContentType "application/json" -Body '{"email":"manager@globex.example.com","password":"PhishGuard!2026"}'
$h = @{ Authorization = "Bearer $($s.access_token)" }

# Analytics overview, filtered by department
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/analytics/overview?department_id=<id>" -Headers $h

# Analyze a pasted email (Indicator Analyst)
Invoke-RestMethod -Method Post "http://127.0.0.1:8001/api/v1/ai/analyze" -Headers $h -ContentType "application/json" `
  -Body (@{ email = "From: IT <it@paypa1.com>`nSubject: urgent`n`nVerify your account immediately" } | ConvertTo-Json)
```

**SSE.** `POST /api/v1/ai/stream` with `{"kind": "analyze|coach|qa|generate_example|chat", "text": "..."}`
streams `event: meta`, then `event: token` (repeated), `event: result` and `event: done`.

**Webhooks.** Each delivery is a `POST` with this JSON body:

```json
{"event": "...", "delivery_id": "...", "data": {...}}
```

Each delivery also carries the header `X-PhishGuard-Signature: t=<unix>,v1=<hex>`, where
`v1 = HMAC_SHA256(secret, "<t>.<raw body>")`. Events: `campaign.activated`, `campaign.completed`,
`report.submitted` and `webhook.test`. A failed delivery is attempted up to 3 times, with 1 s and 2 s backoff.

## Endpoints

### admin

| Method | Path | Summary |
|---|---|---|
| DELETE | `/api/v1/admin/api-keys/{key_id}` | Revoke Key |
| DELETE | `/api/v1/admin/invites/{invite_id}` | Revoke Invite |
| DELETE | `/api/v1/admin/users/{user_id}` | Delete User |
| DELETE | `/api/v1/admin/webhooks/{hook_id}` | Delete Webhook |
| GET | `/api/v1/admin/api-keys` | List Keys |
| GET | `/api/v1/admin/audit` | Audit Log |
| GET | `/api/v1/admin/audit/export.csv` | Audit Export |
| GET | `/api/v1/admin/invites` | List Invites |
| GET | `/api/v1/admin/organizations` | List Orgs |
| GET | `/api/v1/admin/settings` | Get Settings Ep |
| GET | `/api/v1/admin/users` | List Users |
| GET | `/api/v1/admin/webhooks` | List Webhooks |
| GET | `/api/v1/admin/webhooks/{hook_id}/deliveries` | Webhook Deliveries |
| GET | `/api/v1/notifications` | Notifications |
| PATCH | `/api/v1/admin/settings` | Patch Settings |
| PATCH | `/api/v1/admin/users/{user_id}` | Patch User |
| PATCH | `/api/v1/admin/webhooks/{hook_id}` | Toggle Webhook |
| POST | `/api/v1/admin/api-keys` | Create Key |
| POST | `/api/v1/admin/invites` | Create Invite |
| POST | `/api/v1/admin/webhooks` | Create Webhook |
| POST | `/api/v1/admin/webhooks/{hook_id}/test` | Test Webhook |
| POST | `/api/v1/notifications/read-all` | Read All |
| POST | `/api/v1/notifications/{notification_id}/read` | Read One |

### ai

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/ai/status` | Ai Status |
| POST | `/api/v1/ai/analyze` | Analyze |
| POST | `/api/v1/ai/chat` | Chat |
| POST | `/api/v1/ai/coach` | Coach |
| POST | `/api/v1/ai/generate` | Generate |
| POST | `/api/v1/ai/generate/save` | Save Example |
| POST | `/api/v1/ai/qa` | Qa |
| POST | `/api/v1/ai/stream` | Stream |

### analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/analytics/export.csv` | Export Csv |
| GET | `/api/v1/analytics/export.pdf` | Export Pdf |
| GET | `/api/v1/analytics/overview` | Analytics Overview |
| GET | `/api/v1/risk/departments` | Risk Departments |
| GET | `/api/v1/risk/export.csv` | Risk Export |
| GET | `/api/v1/risk/targets` | Risk Targets |
| GET | `/api/v1/risk/targets/{target_id}` | Risk Target |
| POST | `/api/v1/risk/recompute` | Risk Recompute |

### auth

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/auth/me` | Me |
| GET | `/api/v1/auth/me/target` | My Target |
| GET | `/api/v1/auth/oidc/providers` | Oidc Providers |
| PATCH | `/api/v1/auth/me/preferences` | Update Preferences |
| POST | `/api/v1/auth/2fa/disable` | Totp Disable |
| POST | `/api/v1/auth/2fa/setup` | Totp Setup |
| POST | `/api/v1/auth/2fa/verify` | Totp Verify |
| POST | `/api/v1/auth/invite/accept` | Accept Invite |
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/logout` | Logout |
| POST | `/api/v1/auth/oidc/mock/authorize` | Oidc Mock Authorize |
| POST | `/api/v1/auth/oidc/{provider}/callback` | Oidc Callback |
| POST | `/api/v1/auth/password` | Change Password |
| POST | `/api/v1/auth/refresh` | Refresh |

### campaigns

| Method | Path | Summary |
|---|---|---|
| DELETE | `/api/v1/campaigns/{campaign_id}` | Delete Campaign |
| GET | `/api/v1/campaigns` | List Campaigns |
| GET | `/api/v1/campaigns/{campaign_id}` | Get Campaign |
| GET | `/api/v1/campaigns/{campaign_id}/events` | Campaign Events |
| GET | `/api/v1/inbox` | Inbox |
| GET | `/api/v1/inbox/{campaign_id}/preview` | Inbox Preview |
| PATCH | `/api/v1/campaigns/{campaign_id}` | Update Campaign |
| POST | `/api/v1/campaigns` | Create Campaign |
| POST | `/api/v1/campaigns/run-scheduler` | Run Scheduler |
| POST | `/api/v1/campaigns/{campaign_id}/transition` | Transition Campaign |
| POST | `/api/v1/inbox/{campaign_id}/action` | Inbox Action |

### health

| Method | Path | Summary |
|---|---|---|
| GET | `/health/live` | Live |
| GET | `/health/ready` | Ready |

### people

| Method | Path | Summary |
|---|---|---|
| DELETE | `/api/v1/departments/{dept_id}` | Delete Department |
| GET | `/api/v1/departments` | List Departments |
| GET | `/api/v1/targets` | List Targets |
| GET | `/api/v1/targets/{target_id}` | Get Target |
| PATCH | `/api/v1/departments/{dept_id}` | Rename Department |
| POST | `/api/v1/departments` | Create Department |
| POST | `/api/v1/targets/generate-synthetic` | Generate Synthetic |

### report-phish

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/reports` | Triage Queue |
| GET | `/api/v1/reports/mine` | My Reports |
| GET | `/api/v1/reports/{report_id}` | Get Report |
| POST | `/api/v1/reports` | Submit Report |
| POST | `/api/v1/reports/{report_id}/triage` | Triage |

### templates

| Method | Path | Summary |
|---|---|---|
| DELETE | `/api/v1/templates/{template_id}` | Delete Template |
| GET | `/api/v1/templates` | List Templates |
| GET | `/api/v1/templates/meta` | Template Meta |
| GET | `/api/v1/templates/{template_id}` | Get Template |
| GET | `/api/v1/templates/{template_id}/preview` | Preview Template |
| GET | `/api/v1/templates/{template_id}/versions` | Template Versions |
| PATCH | `/api/v1/templates/{template_id}` | Update Template |
| POST | `/api/v1/templates` | Create Template |

### training

| Method | Path | Summary |
|---|---|---|
| DELETE | `/api/v1/training/modules/{module_id}` | Delete Module |
| GET | `/api/v1/training/badges/me` | My Badges |
| GET | `/api/v1/training/certificates` | My Certificates |
| GET | `/api/v1/training/certificates/{cert_id}/pdf` | Certificate Download |
| GET | `/api/v1/training/enrollments` | List Enrollments |
| GET | `/api/v1/training/leaderboard` | Leaderboard |
| GET | `/api/v1/training/modules` | List Modules |
| GET | `/api/v1/training/modules/{module_id}` | Get Module |
| GET | `/api/v1/training/my` | My Training |
| POST | `/api/v1/training/enrollments` | Assign |
| POST | `/api/v1/training/enrollments/{enrollment_id}/lessons/{lesson_id}/complete` | Complete Lesson Ep |
| POST | `/api/v1/training/enrollments/{enrollment_id}/quiz` | Submit Quiz |
| POST | `/api/v1/training/modules` | Create Module |

