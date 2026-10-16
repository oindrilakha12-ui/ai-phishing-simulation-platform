"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/components/providers";
import { Button, Card, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SessionInfo } from "@/lib/types";

export default function InvitePage() {
  const router = useRouter();
  const { setSession } = useAuth();
  const [form, setForm] = useState({ code: "", full_name: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSession(await api<SessionInfo>("/auth/invite/accept", { method: "POST", body: form }));
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.details)) {
        setError(err.details.map((d: { msg?: string }) => d.msg).join("; "));
      } else setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <Card title="Accept an invite">
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Input label="Invite code" required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          <Input label="Full name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input
            label="Password"
            type="password"
            hint="At least 12 characters with upper- and lower-case letters, a digit and a symbol."
            autoComplete="new-password"
            required
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
          <Button type="submit" loading={busy}>
            Create account
          </Button>
        </form>
      </Card>
    </main>
  );
}
