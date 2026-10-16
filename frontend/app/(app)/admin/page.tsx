"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Input, Loading, PageHeader, Pagination, Select, Table, Tabs } from "@/components/ui";
import { api, download } from "@/lib/api";
import { dt } from "@/lib/format";
import type { Page, User } from "@/lib/types";

type Tab = "users" | "keys" | "webhooks" | "audit" | "settings";

function OneTimeSecret({ label, value, onClose }: { label: string; value: string; onClose: () => void }) {
  return (
    <div role="alert" className="mb-3 rounded-md border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
      <b>{label}</b> (shown once — copy it now):
      <code className="mt-1 block break-all rounded bg-white p-2 dark:bg-slate-900">{value}</code>
      <Button variant="secondary" className="mt-2" onClick={onClose}>I have copied it</Button>
    </div>
  );
}

function UsersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [invite, setInvite] = useState({ email: "", role: "learner" });
  const [code, setCode] = useState<string | null>(null);
  const users = useQuery({ queryKey: ["admin-users", page, q], queryFn: () => api<Page<User & { locked_until?: string }>>("/admin/users", { query: { page, page_size: 15, q } }), placeholderData: (p) => p });
  const patch = async (id: string, body: Record<string, unknown>) => {
    try {
      await api(`/admin/users/${id}`, { method: "PATCH", body });
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.push("success", "User updated");
    } catch (e) {
      toast.error(e);
    }
  };
  return (
    <div className="space-y-4">
      <Card title="Invite a user (in-app code — no email is sent)">
        {code && <OneTimeSecret label="Invite code" value={code} onClose={() => setCode(null)} />}
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const r = await api<{ code: string }>("/admin/invites", { method: "POST", body: invite });
              setCode(r.code);
              setInvite({ email: "", role: "learner" });
            } catch (err) {
              toast.error(err);
            }
          }}
        >
          <Input label="Email" type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
          <Select label="Role" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
            <option value="learner">learner</option><option value="manager">manager</option><option value="org_admin">org_admin</option>
          </Select>
          <Button type="submit">Create invite code</Button>
        </form>
      </Card>
      <Card title="Users">
        <div className="mb-3 max-w-xs"><Input label="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        {users.data && (
          <>
            <Table caption="Users" head={["Name", "Email", "Role", "2FA", "Status", "Last login", "Actions"]}>
              {users.data.items.map((u) => (
                <tr key={u.id}>
                  <td className="px-2 py-1">{u.full_name}</td>
                  <td className="px-2 py-1">{u.email}</td>
                  <td className="px-2 py-1">
                    <select aria-label={`Role for ${u.full_name}`} className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-sm dark:border-slate-600" value={u.role} disabled={u.role === "super_admin"} onChange={(e) => patch(u.id, { role: e.target.value })}>
                      {u.role === "super_admin" && <option>super_admin</option>}
                      <option>org_admin</option><option>manager</option><option>learner</option>
                    </select>
                  </td>
                  <td className="px-2 py-1">{u.totp_enabled ? <Badge tone="green">on</Badge> : <Badge>off</Badge>}</td>
                  <td className="px-2 py-1">{u.is_active ? <Badge tone="green">active</Badge> : <Badge tone="red">inactive</Badge>}</td>
                  <td className="px-2 py-1">{dt(u.last_login_at)}</td>
                  <td className="px-2 py-1 space-x-2 whitespace-nowrap">
                    <button className="text-sm text-blue-700 hover:underline dark:text-blue-400" onClick={() => patch(u.id, { is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Activate"}</button>
                    <button className="text-sm text-blue-700 hover:underline dark:text-blue-400" onClick={() => patch(u.id, { unlock: true })}>Unlock</button>
                  </td>
                </tr>
              ))}
            </Table>
            <Pagination page={page} pageSize={15} total={users.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}

type Key = { id: string; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null; revoked_at: string | null };

function KeysTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api<Page<Key>>("/admin/api-keys", { query: { page_size: 50 } }) });
  return (
    <Card title="API keys (hashed at rest, read-only scopes)">
      {secret && <OneTimeSecret label="API key" value={secret} onClose={() => setSecret(null)} />}
      <form
        className="mb-4 flex flex-wrap items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api<{ key: string }>("/admin/api-keys", { method: "POST", body: { name, scopes: ["analytics:read"] } });
            setSecret(r.key);
            setName("");
            qc.invalidateQueries({ queryKey: ["api-keys"] });
          } catch (err) {
            toast.error(err);
          }
        }}
      >
        <Input label="Key name" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} />
        <p className="text-sm">Scope: <Badge>analytics:read</Badge></p>
        <Button type="submit">Create key</Button>
      </form>
      {keys.data?.items.length === 0 && <EmptyState title="No API keys" />}
      {keys.data && keys.data.items.length > 0 && (
        <Table caption="API keys" head={["Name", "Prefix", "Scopes", "Created", "Last used", "Status", ""]}>
          {keys.data.items.map((k) => (
            <tr key={k.id}>
              <td className="px-2 py-1">{k.name}</td>
              <td className="px-2 py-1"><code>{k.prefix}…</code></td>
              <td className="px-2 py-1">{k.scopes.join(", ")}</td>
              <td className="px-2 py-1">{dt(k.created_at)}</td>
              <td className="px-2 py-1">{dt(k.last_used_at)}</td>
              <td className="px-2 py-1">{k.revoked_at ? <Badge tone="red">revoked</Badge> : <Badge tone="green">active</Badge>}</td>
              <td className="px-2 py-1">
                {!k.revoked_at && (
                  <button className="text-sm text-red-700 hover:underline" onClick={async () => { await api(`/admin/api-keys/${k.id}`, { method: "DELETE" }).catch(toast.error); qc.invalidateQueries({ queryKey: ["api-keys"] }); }}>
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

type Hook = { id: string; url: string; events: string[]; is_active: boolean; created_at: string; secret_preview: string };
type Delivery = { id: string; event: string; status: string; attempts: number; response_code: number | null; last_error: string | null; created_at: string };

function WebhooksTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const hooks = useQuery({ queryKey: ["webhooks"], queryFn: () => api<Page<Hook>>("/admin/webhooks", { query: { page_size: 50 } }) });
  const deliveries = useQuery({ queryKey: ["deliveries", open], queryFn: () => api<Page<Delivery>>(`/admin/webhooks/${open}/deliveries`, { query: { page_size: 20 } }), enabled: !!open, refetchInterval: 3000 });
  return (
    <Card title="Webhooks (HMAC-SHA256 signed JSON to registered URLs only — never email)">
      {secret && <OneTimeSecret label="Signing secret" value={secret} onClose={() => setSecret(null)} />}
      <form
        className="mb-4 flex flex-wrap items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api<{ secret: string }>("/admin/webhooks", { method: "POST", body: { url, events: ["*"] } });
            setSecret(r.secret);
            setUrl("");
            qc.invalidateQueries({ queryKey: ["webhooks"] });
          } catch (err) {
            toast.error(err);
          }
        }}
      >
        <div className="min-w-72 flex-1"><Input label="Endpoint URL" type="url" required placeholder="https://hooks.example/phishguard" value={url} onChange={(e) => setUrl(e.target.value)} /></div>
        <Button type="submit">Add webhook</Button>
      </form>
      {hooks.data?.items.length === 0 && <EmptyState title="No webhooks registered" />}
      {hooks.data && hooks.data.items.length > 0 && (
        <Table caption="Webhooks" head={["URL", "Events", "Status", "Actions"]}>
          {hooks.data.items.map((h) => (
            <tr key={h.id}>
              <td className="break-all px-2 py-1">{h.url}</td>
              <td className="px-2 py-1">{h.events.join(", ")}</td>
              <td className="px-2 py-1">{h.is_active ? <Badge tone="green">active</Badge> : <Badge>paused</Badge>}</td>
              <td className="space-x-2 whitespace-nowrap px-2 py-1 text-sm">
                <button className="text-blue-700 hover:underline dark:text-blue-400" onClick={async () => { await api(`/admin/webhooks/${h.id}/test`, { method: "POST" }).catch(toast.error); setOpen(h.id); toast.push("info", "Test delivery queued"); }}>Send test</button>
                <button className="text-blue-700 hover:underline dark:text-blue-400" onClick={() => setOpen(open === h.id ? null : h.id)}>Delivery log</button>
                <button className="text-blue-700 hover:underline dark:text-blue-400" onClick={async () => { await api(`/admin/webhooks/${h.id}`, { method: "PATCH", query: { is_active: !h.is_active } }).catch(toast.error); qc.invalidateQueries({ queryKey: ["webhooks"] }); }}>{h.is_active ? "Pause" : "Resume"}</button>
                <button className="text-red-700 hover:underline" onClick={async () => { await api(`/admin/webhooks/${h.id}`, { method: "DELETE" }).catch(toast.error); qc.invalidateQueries({ queryKey: ["webhooks"] }); }}>Delete</button>
              </td>
            </tr>
          ))}
        </Table>
      )}
      {open && deliveries.data && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold">Delivery log (retries with exponential backoff, max 3 attempts)</h3>
          <Table caption="Deliveries" head={["When", "Event", "Status", "Attempts", "HTTP", "Last error"]}>
            {deliveries.data.items.map((d) => (
              <tr key={d.id}>
                <td className="px-2 py-1">{dt(d.created_at)}</td>
                <td className="px-2 py-1">{d.event}</td>
                <td className="px-2 py-1"><Badge tone={d.status === "success" ? "green" : d.status === "failed" ? "red" : "amber"}>{d.status}</Badge></td>
                <td className="px-2 py-1">{d.attempts}</td>
                <td className="px-2 py-1">{d.response_code ?? "—"}</td>
                <td className="break-all px-2 py-1 text-xs">{d.last_error ?? "—"}</td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </Card>
  );
}

type Audit = { id: string; created_at: string; actor_email: string | null; action: string; entity_type: string; entity_id: string | null; ip: string | null; request_id: string | null; details: Record<string, unknown> };

function AuditTab() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [f, setF] = useState({ action: "", actor: "", date_from: "", date_to: "" });
  const query = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || undefined]));
  const q = useQuery({ queryKey: ["audit", page, f], queryFn: () => api<Page<Audit>>("/admin/audit", { query: { ...query, page, page_size: 20 } }), placeholderData: (p) => p });
  return (
    <Card title="Audit log" actions={<Button variant="secondary" onClick={() => download("/admin/audit/export.csv", "phishguard-audit.csv", query).catch(toast.error)}>Export CSV</Button>}>
      <div className="mb-3 grid gap-3 sm:grid-cols-4">
        <Input label="Action prefix" placeholder="campaign." value={f.action} onChange={(e) => { setF({ ...f, action: e.target.value }); setPage(1); }} />
        <Input label="Actor email" value={f.actor} onChange={(e) => { setF({ ...f, actor: e.target.value }); setPage(1); }} />
        <Input label="From" type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
        <Input label="To" type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
      </div>
      {q.isLoading && <Loading />}
      {q.data && (
        <>
          <Table caption="Audit entries" head={["When", "Who", "Action", "Entity", "IP", "Details"]}>
            {q.data.items.map((a) => (
              <tr key={a.id} className="align-top">
                <td className="whitespace-nowrap px-2 py-1">{dt(a.created_at)}</td>
                <td className="px-2 py-1">{a.actor_email ?? "—"}</td>
                <td className="px-2 py-1"><code>{a.action}</code></td>
                <td className="px-2 py-1">{a.entity_type}{a.entity_id ? ` · ${a.entity_id.slice(0, 8)}` : ""}</td>
                <td className="px-2 py-1">{a.ip}</td>
                <td className="max-w-xs break-all px-2 py-1 text-xs">{Object.keys(a.details).length ? JSON.stringify(a.details) : "—"}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={20} total={q.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}

type OrgSettings = { id: string; name: string; slug: string; settings: { leaderboard_individuals_enabled?: boolean; risk_high_threshold?: number; training_pass_mark_default?: number } };

function SettingsTab() {
  const toast = useToast();
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["org-settings"], queryFn: () => api<OrgSettings>("/admin/settings") });
  const [draft, setDraft] = useState<OrgSettings | null>(null);
  if (!s.data) return <Loading />;
  const v = draft ?? s.data;
  return (
    <Card title="Organization settings">
      <form
        className="flex max-w-md flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/admin/settings", { method: "PATCH", body: { name: v.name, ...v.settings } });
            qc.invalidateQueries({ queryKey: ["org-settings"] });
            setDraft(null);
            toast.push("success", "Settings saved");
          } catch (err) {
            toast.error(err);
          }
        }}
      >
        <Input label="Organization name" value={v.name} onChange={(e) => setDraft({ ...v, name: e.target.value })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!v.settings.leaderboard_individuals_enabled} onChange={(e) => setDraft({ ...v, settings: { ...v.settings, leaderboard_individuals_enabled: e.target.checked } })} />
          Allow individual leaderboard entries (people must still opt in)
        </label>
        <Input label="High-risk threshold" type="number" min={30} max={95} value={v.settings.risk_high_threshold ?? 60} onChange={(e) => setDraft({ ...v, settings: { ...v.settings, risk_high_threshold: Number(e.target.value) } })} />
        <Button type="submit">Save settings</Button>
      </form>
    </Card>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("users");
  return (
    <>
      <PageHeader title="Admin" subtitle="Users, API keys, webhooks, audit log and organization settings. Every change is audited." />
      <Tabs
        label="Admin sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "users", label: "Users & invites" },
          { id: "keys", label: "API keys" },
          { id: "webhooks", label: "Webhooks" },
          { id: "audit", label: "Audit log" },
          { id: "settings", label: "Settings" },
        ]}
      />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "users" && <UsersTab />}
        {tab === "keys" && <KeysTab />}
        {tab === "webhooks" && <WebhooksTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "settings" && <SettingsTab />}
      </div>
    </>
  );
}
