"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "@/components/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Input, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export default function ProfilePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  if (!user) return null;
  const refresh = () => qc.invalidateQueries({ queryKey: ["me"] });

  return (
    <>
      <PageHeader title="Profile" subtitle={`${user.full_name} · ${user.email} · ${user.role}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={<span>Two-factor authentication {user.totp_enabled ? <Badge tone="green">enabled</Badge> : <Badge>off</Badge>}</span>}>
          {!user.totp_enabled && !setup && (
            <Button onClick={async () => { try { setSetup(await api<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup", { method: "POST" })); } catch (e) { toast.error(e); } }}>Set up 2FA</Button>
          )}
          {setup && (
            <div className="space-y-2 text-sm">
              <p>Add this secret to an authenticator app (Google Authenticator, Authy, 1Password…), then enter the 6-digit code.</p>
              <code className="block break-all rounded bg-slate-100 p-2 dark:bg-slate-800">{setup.secret}</code>
              <p className="break-all text-xs text-slate-500">{setup.otpauth_uri}</p>
            </div>
          )}
          {(setup || user.totp_enabled) && (
            <form
              className="mt-3 flex items-end gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await api(user.totp_enabled ? "/auth/2fa/disable" : "/auth/2fa/verify", { method: "POST", body: { code } });
                  toast.push("success", user.totp_enabled ? "2FA disabled" : "2FA enabled");
                  setSetup(null);
                  setCode("");
                  refresh();
                } catch (err) {
                  toast.error(err);
                }
              }}
            >
              <Input label="6-digit code" inputMode="numeric" pattern="\d{6}" required value={code} onChange={(e) => setCode(e.target.value)} />
              <Button type="submit" variant={user.totp_enabled ? "danger" : "primary"}>{user.totp_enabled ? "Disable 2FA" : "Verify & enable"}</Button>
            </form>
          )}
        </Card>
        <Card title="Leaderboard privacy">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={user.leaderboard_opt_in}
              onChange={async (e) => {
                try {
                  await api("/auth/me/preferences", { method: "PATCH", body: { leaderboard_opt_in: e.target.checked } });
                  refresh();
                } catch (err) {
                  toast.error(err);
                }
              }}
            />
            Show my name on the individual leaderboard (off by default; departments are always shown in aggregate)
          </label>
        </Card>
        <Card title="Change password">
          <form
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api("/auth/password", { method: "POST", body: pw });
                toast.push("success", "Password updated");
                setPw({ current_password: "", new_password: "" });
              } catch (err) {
                toast.error(err);
              }
            }}
          >
            <Input label="Current password" type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
            <Input label="New password" type="password" autoComplete="new-password" hint="12+ characters, upper & lower case, a digit and a symbol." required value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            <Button type="submit">Update password</Button>
          </form>
        </Card>
      </div>
    </>
  );
}
