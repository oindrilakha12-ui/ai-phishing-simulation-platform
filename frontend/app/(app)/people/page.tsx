"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "@/components/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Loading, PageHeader, Pagination, Select, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { atLeast } from "@/lib/format";
import type { Department, Page } from "@/lib/types";

type Target = { id: string; full_name: string; email: string; department_id: string; department_name: string; user_id: string | null; is_synthetic: boolean };
type TargetDetail = Target & {
  event_counts: Record<string, number>;
  risk: { score: number; level: string; factors: { label: string; impact: number; detail: string }[] } | null;
  enrollments: { id: string; module: string; status: string; source: string }[];
};

function Detail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["target", id], queryFn: () => api<TargetDetail>(`/targets/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const t = q.data!;
  return (
    <Card title={`${t.full_name} — ${t.department_name}`}>
      <p className="mb-2 text-sm">
        Risk: <b>{t.risk?.score}</b> <Badge tone={t.risk?.level === "high" ? "red" : t.risk?.level === "medium" ? "amber" : "green"}>{t.risk?.level}</Badge>
      </p>
      <ul className="mb-3 space-y-1 text-sm">
        {t.risk?.factors.map((f) => (
          <li key={f.label} className="flex justify-between gap-2">
            <span>{f.label} <span className="text-slate-500">({f.detail})</span></span>
            <span className={f.impact > 0 ? "text-red-700 dark:text-red-400" : "text-green-700 dark:text-green-400"}>{f.impact > 0 ? "+" : ""}{f.impact}</span>
          </li>
        ))}
      </ul>
      <p className="text-sm">Events: {Object.entries(t.event_counts).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</p>
      <p className="mt-2 text-sm">Training: {t.enrollments.map((e) => `${e.module} (${e.status}${e.source === "auto" ? ", auto" : ""})`).join("; ") || "none"}</p>
    </Card>
  );
}

export default function PeoplePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [newDept, setNewDept] = useState("");
  const [gen, setGen] = useState({ department_id: "", count: 5 });
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Page<Department>>("/departments", { query: { page_size: 100 } }) });
  const targets = useQuery({
    queryKey: ["targets", page, q, dept],
    queryFn: () => api<Page<Target>>("/targets", { query: { page, page_size: 15, q, department_id: dept } }),
    placeholderData: (p) => p,
  });
  const isAdmin = atLeast(user?.role, "org_admin");

  return (
    <>
      <PageHeader title="Learners & departments" subtitle="Every person here is SYNTHETIC (generated with Faker). There is no real-contact import." />
      {isAdmin && (
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <Card title="Add department">
            <form
              className="flex items-end gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await api("/departments", { method: "POST", body: { name: newDept } });
                  setNewDept("");
                  qc.invalidateQueries({ queryKey: ["departments"] });
                  toast.push("success", "Department added");
                } catch (err) {
                  toast.error(err);
                }
              }}
            >
              <div className="flex-1"><Input label="Name" required minLength={2} value={newDept} onChange={(e) => setNewDept(e.target.value)} /></div>
              <Button type="submit">Add</Button>
            </form>
          </Card>
          <Card title="Generate synthetic people">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  const r = await api<{ message: string }>("/targets/generate-synthetic", { method: "POST", body: gen });
                  qc.invalidateQueries({ queryKey: ["targets"] });
                  toast.push("success", r.message);
                } catch (err) {
                  toast.error(err);
                }
              }}
            >
              <Select label="Department" required value={gen.department_id} onChange={(e) => setGen({ ...gen, department_id: e.target.value })}>
                <option value="">Choose…</option>
                {depts.data?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
              <Input label="How many" type="number" min={1} max={100} value={gen.count} onChange={(e) => setGen({ ...gen, count: Number(e.target.value) })} />
              <Button type="submit">Generate</Button>
            </form>
          </Card>
        </div>
      )}
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Input label="Search people" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select label="Department" value={dept} onChange={(e) => { setDept(e.target.value); setPage(1); }}>
          <option value="">All departments</option>
          {depts.data?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </Select>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div>
          {targets.isLoading && <Loading />}
          {targets.error && <ErrorState error={targets.error} />}
          {targets.data?.items.length === 0 && <EmptyState title="No people found" />}
          {targets.data && targets.data.items.length > 0 && (
            <>
              <Table caption="Synthetic people" head={["Name", "Email", "Department", "Account"]}>
                {targets.data.items.map((t) => (
                  <tr key={t.id} className={selected === t.id ? "bg-blue-50 dark:bg-blue-950" : ""}>
                    <td className="px-2 py-1">
                      <button className="font-medium text-blue-700 hover:underline dark:text-blue-400" onClick={() => setSelected(t.id)}>{t.full_name}</button>
                    </td>
                    <td className="px-2 py-1 text-slate-600 dark:text-slate-400">{t.email}</td>
                    <td className="px-2 py-1">{t.department_name}</td>
                    <td className="px-2 py-1">{t.user_id ? <Badge tone="blue">learner login</Badge> : <Badge>synthetic</Badge>}</td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} pageSize={15} total={targets.data.total} onPage={setPage} />
            </>
          )}
        </div>
        <div>{selected ? <Detail id={selected} /> : <EmptyState title="Select a person" hint="See their explained risk score and training." />}</div>
      </div>
    </>
  );
}
