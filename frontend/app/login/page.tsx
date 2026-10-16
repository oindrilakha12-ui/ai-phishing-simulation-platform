"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useAuth } from "@/components/providers";
import { Button, Card, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";
import type { SessionInfo } from "@/lib/types";

const DEMO_ACCOUNTS = [
  ["admin@globex.example.com", "Org admin"],
  ["manager@globex.example.com", "Manager"],
  ["learner@globex.example.com", "Learner"],
  ["superadmin@globex.example.com", "Super admin"],
];

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { setSession } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/"; // no open redirects

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api<SessionInfo>("/auth/login", {
        method: "POST",
        body: { email, password, ...(needTotp ? { totp_code: totp } : {}) },
      });
      setSession(s);
      router.replace(safeNext);
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") {
        setNeedTotp(true);
        setError(null);
      } else setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-4">
      <div className="text-center">
        <h1 className="text-3xl font-bold">{t.appName}</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t.tagline}</p>
      </div>
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-3" aria-describedby={error ? "login-error" : undefined}>
          {!needTotp ? (
            <>
              <Input label="Email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
              <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </>
          ) : (
            <Input
              label="Two-factor code"
              hint="Enter the 6-digit code from your authenticator app."
              inputMode="numeric"
              pattern="\d{6}"
              autoComplete="one-time-code"
              autoFocus
              required
              value={totp}
              onChange={(e) => setTotp(e.target.value)}
            />
          )}
          {error && (
            <p id="login-error" role="alert" className="text-sm text-red-700 dark:text-red-400">
              {error}
            </p>
          )}
          <Button type="submit" loading={busy}>
            {needTotp ? "Verify" : "Sign in"}
          </Button>
        </form>
        <div className="mt-4 flex flex-wrap justify-between gap-2 text-sm">
          <Link href="/sso/mock" className="text-blue-700 hover:underline dark:text-blue-400">
            Sign in with SSO (mock IdP)
          </Link>
          <Link href="/invite" className="text-blue-700 hover:underline dark:text-blue-400">
            I have an invite code
          </Link>
        </div>
      </Card>
      <Card title="Demo accounts (synthetic)">
        <p className="mb-2 text-xs text-slate-600 dark:text-slate-400">
          Password for all: <code>PhishGuard!2026</code> (development only)
        </p>
        <ul className="grid grid-cols-2 gap-2">
          {DEMO_ACCOUNTS.map(([e, label]) => (
            <li key={e}>
              <button
                type="button"
                className="w-full rounded border border-slate-200 p-2 text-left text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                onClick={() => {
                  setEmail(e);
                  setPassword("PhishGuard!2026");
                }}
              >
                <span className="block font-semibold">{label}</span>
                {e}
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
