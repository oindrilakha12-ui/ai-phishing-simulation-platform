"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/components/providers";
import { Badge, Button, Card, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SessionInfo } from "@/lib/types";

/** Stands in for an external identity provider's consent screen (demo only). */
export default function MockSSO() {
  const router = useRouter();
  const { setSession } = useAuth();
  const [email, setEmail] = useState("manager@globex.example.com");
  const [error, setError] = useState<string | null>(null);

  async function go(e: React.FormEvent) {
    e.preventDefault();
    try {
      const { code } = await api<{ code: string }>("/auth/oidc/mock/authorize", { method: "POST", body: { email } });
      setSession(await api<SessionInfo>("/auth/oidc/mock/callback", { method: "POST", body: { code } }));
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "SSO failed");
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <Card title={<span>Mock identity provider <Badge tone="amber">DEMO ONLY</Badge></span>}>
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
          This simulates an OIDC sign-in. A real IdP (Entra ID, Okta…) would plug into the same backend interface; see
          docs/ARCHITECTURE.md. Real IdP integration is not implemented.
        </p>
        <form onSubmit={go} className="flex flex-col gap-3">
          <Input label="Identity (email)" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
          <Button type="submit">Continue as this identity</Button>
        </form>
      </Card>
    </main>
  );
}
