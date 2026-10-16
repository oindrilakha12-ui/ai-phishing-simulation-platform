"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Loading, PageHeader, Pagination, Select, STATUS_TONE, Table, Textarea, TLink } from "@/components/ui";
import { api } from "@/lib/api";
import { d } from "@/lib/format";
import type { Page, RedFlag, Template } from "@/lib/types";

type Meta = { fictional_brands: string[]; red_flag_categories: string[]; watermark: string };

function CreateTemplate({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const meta = useQuery({ queryKey: ["template-meta"], queryFn: () => api<Meta>("/templates/meta") });
  const [f, setF] = useState({
    name: "", brand: "Globex", category: "credentials", difficulty: "easy", subject: "", sender_name: "",
    sender_email: "notice@globex-alerts.example", body_html: "<p>Dear employee,</p><p>…</p>",
  });
  const [flags, setFlags] = useState<RedFlag[]>([{ id: "f1", category: "greeting", description: "", cue: "" }]);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/templates", { method: "POST", body: { ...f, red_flags: flags } });
      toast.push("success", "Template created (watermark enforced)");
      onDone();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="New training template" className="mb-4">
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
        Rules: fictional brands only, sender and links on reserved <code>.example</code> domains, at least one red flag, no forms/scripts.
        The “{meta.data?.watermark}” banner is added automatically.
      </p>
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <Input label="Name" required value={f.name} onChange={set("name")} />
        <Select label="Fictional brand" value={f.brand} onChange={set("brand")}>
          {meta.data?.fictional_brands.map((b) => <option key={b}>{b}</option>)}
        </Select>
        <Input label="Category" value={f.category} onChange={set("category")} />
        <Select label="Difficulty" value={f.difficulty} onChange={set("difficulty")}>
          <option>easy</option><option>medium</option><option>hard</option>
        </Select>
        <Input label="Subject" required value={f.subject} onChange={set("subject")} />
        <Input label="Sender name" required value={f.sender_name} onChange={set("sender_name")} />
        <Input label="Sender email (.example only)" required value={f.sender_email} onChange={set("sender_email")} />
        <div className="md:col-span-2">
          <Textarea label="Body HTML (sanitised on preview)" rows={5} value={f.body_html} onChange={set("body_html")} />
        </div>
        <fieldset className="md:col-span-2">
          <legend className="mb-2 text-sm font-medium">Red flags</legend>
          {flags.map((fl, i) => (
            <div key={i} className="mb-2 grid gap-2 md:grid-cols-[140px_1fr_1fr_auto]">
              <Select label={`Flag ${i + 1} category`} value={fl.category} onChange={(e) => setFlags(flags.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)))}>
                {meta.data?.red_flag_categories.map((c) => <option key={c}>{c}</option>)}
              </Select>
              <Input label="Why it's suspicious" required value={fl.description} onChange={(e) => setFlags(flags.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
              <Input label="Cue (exact text to highlight)" value={fl.cue} onChange={(e) => setFlags(flags.map((x, j) => (j === i ? { ...x, cue: e.target.value } : x)))} />
              <Button type="button" variant="ghost" className="self-end" aria-label={`Remove flag ${i + 1}`} disabled={flags.length === 1} onClick={() => setFlags(flags.filter((_, j) => j !== i))}>✕</Button>
            </div>
          ))}
          <Button type="button" variant="secondary" onClick={() => setFlags([...flags, { id: `f${flags.length + 1}`, category: "link", description: "", cue: "" }])}>
            Add red flag
          </Button>
        </fieldset>
        <div className="md:col-span-2"><Button type="submit" loading={busy}>Create template</Button></div>
      </form>
    </Card>
  );
}

export default function TemplatesPage() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [difficulty, setDifficulty] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["templates", page, difficulty, q],
    queryFn: () => api<Page<Template>>("/templates", { query: { page, page_size: 10, difficulty, q } }),
    placeholderData: (p) => p,
  });
  return (
    <>
      <PageHeader
        title="Templates & preview sandbox"
        subtitle="Fictional-brand, watermarked training lures with annotated red flags."
        actions={<Button onClick={() => setCreating((c) => !c)}>{creating ? "Close" : "New template"}</Button>}
      />
      {creating && <CreateTemplate onDone={() => { setCreating(false); qc.invalidateQueries({ queryKey: ["templates"] }); }} />}
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Input label="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select label="Difficulty" value={difficulty} onChange={(e) => { setDifficulty(e.target.value); setPage(1); }}>
          <option value="">All</option><option>easy</option><option>medium</option><option>hard</option>
        </Select>
      </div>
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.data?.items.length === 0 && <EmptyState title="No templates found" />}
      {list.data && list.data.items.length > 0 && (
        <>
          <Table caption="Templates" head={["Name", "Brand", "Difficulty", "Red flags", "Version", "Source", "Updated"]}>
            {list.data.items.map((t) => (
              <tr key={t.id}>
                <td className="px-2 py-2"><TLink href={`/templates/${t.id}`}>{t.name}</TLink></td>
                <td className="px-2 py-2">{t.brand}</td>
                <td className="px-2 py-2"><Badge tone={STATUS_TONE[t.difficulty] ?? "amber"}>{t.difficulty}</Badge></td>
                <td className="px-2 py-2">{t.red_flags.length}</td>
                <td className="px-2 py-2">v{t.version}</td>
                <td className="px-2 py-2">{t.source === "ai_demo" ? <Badge tone="amber">AI (demo)</Badge> : t.source}</td>
                <td className="px-2 py-2">{d(t.updated_at)}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={10} total={list.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
