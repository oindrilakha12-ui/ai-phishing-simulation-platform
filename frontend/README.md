# PhishGuard frontend

The PhishGuard frontend, built with Next.js 16 (App Router), TypeScript, Tailwind 4, TanStack Query and Recharts.
See the [root README](../README.md) for setup.

```powershell
npm install
npm run dev            # http://localhost:3000; proxies /api/v1 -> $env:BACKEND_URL (default http://127.0.0.1:8001)
npm run lint           # eslint
npm run typecheck      # tsc --noEmit
npm test               # vitest + React Testing Library
npx playwright test    # E2E smoke tests (needs backend + frontend running; uses installed Edge)
```

| Folder | Contents |
|---|---|
| `app/(app)/` | Authenticated pages behind the role-aware `AppShell` |
| `app/login`, `app/invite`, `app/sso/mock` | Public pages |
| `components/` | UI primitives, providers (React Query, auth, theme, toasts), preview sandbox, charts |
| `lib/api.ts` | Fetch wrapper: cookies, CSRF header, refresh-on-expiry, SSE reader |
| `lib/i18n.ts` | Dictionary-based i18n scaffold |
