"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "@/components/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Pagination, Select, STATUS_TONE, Table, TLink } from "@/components/ui";
import { api, download } from "@/lib/api";
import { atLeast, d } from "@/lib/format";
import type { Department, Page } from "@/lib/types";

type Enrollment = { id: string; module_title: string; category: string; status: string; source: string; progress_pct: number; completed_at: string | null; target_name?: string };
type Module = { id: string; title: string; description: string; category: string; est_minutes: number; lessons: { id: string; title: string }[] };
type Cert = { id: string; serial: string; module_title: string; issued_at: string };
type Leaderboard = { departments: { department: string; avg_points: number; people: number }[]; individuals: { name: string; points: number }[]; privacy_note: string };

function Leaderboards() {
  const lb = useQuery({ queryKey: ["leaderboard"], queryFn: () => api<Leaderboard>("/training/leaderboard") });
  if (!lb.data) return <Loading />;
  return (
    <Card title="Leaderboard">
      <p className="mb-2 text-xs text-slate-600 dark:text-slate-400">{lb.data.privacy_note}</p>
      <div className="grid gap-4 md:grid-cols-2">
        <Table caption="Department leaderboard" head={["Department", "Avg points", "People"]}>
          {lb.data.departments.map((r) => (
            <tr key={r.department}><td className="px-2 py-1">{r.department}</td><td className="px-2 py-1">{r.avg_points}</td><td className="px-2 py-1">{r.people}</td></tr>
          ))}
        </Table>
        <Table caption="Opted-in individuals" head={["Person (opted in)", "Points"]}>
          {lb.data.individuals.map((r) => (
            <tr key={r.name}><td className="px-2 py-1">{r.name}</td><td className="px-2 py-1">{r.points}</td></tr>
          ))}
        </Table>
      </div>
    </Card>
  );
}

function LearnerTraining() {
  const my = useQuery({ queryKey: ["my-training"], queryFn: () => api<Enrollment[]>("/training/my") });
  const certs = useQuery({ queryKey: ["certs"], queryFn: () => api<Cert[]>("/training/certificates") });
  const toast = useToast();
  return (
    <div className="space-y-4">
      <Card title="My modules">
        {my.isLoading && <Loading />}
        {my.error && <ErrorState error={my.error} />}
        {my.data?.length === 0 && <EmptyState title="No training assigned" hint="Modules are assigned by your manager or automatically after a simulation." />}
        {my.data && my.data.length > 0 && (
          <Table caption="My modules" head={["Module", "Status", "Progress", "Assigned by"]}>
            {my.data.map((e) => (
              <tr key={e.id}>
                <td className="px-2 py-2"><TLink href={`/training/${e.id}`}>{e.module_title}</TLink></td>
                <td className="px-2 py-2"><Badge tone={STATUS_TONE[e.status]}>{e.status.replace("_", " ")}</Badge></td>
                <td className="px-2 py-2">
                  <div className="h-2 w-32 rounded bg-slate-200 dark:bg-slate-700" role="progressbar" aria-valuenow={e.progress_pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${e.module_title} progress`}>
                    <div className="h-2 rounded bg-blue-700" style={{ width: `${e.progress_pct}%` }} />
                  </div>
                </td>
                <td className="px-2 py-2">{e.source === "auto" ? "Automatic (after a simulation)" : "Manager"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Card title="Certificates">
        {certs.data?.length === 0 && <EmptyState title="No certificates yet" />}
        <ul className="space-y-2 text-sm">
          {certs.data?.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2">
              <span>{c.module_title} · {d(c.issued_at)} · <code>{c.serial}</code></span>
              <Button variant="secondary" onClick={() => download(`/training/certificates/${c.id}/pdf`, `certificate-${c.serial}.pdf`).catch(toast.error)}>Download PDF</Button>
            </li>
          ))}
        </ul>
      </Card>
      <Leaderboards />
    </div>
  );
}

function ManagerTraining() {
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [assign, setAssign] = useState({ module_id: "", department_id: "" });
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api<Page<Module>>("/training/modules", { query: { page_size: 100 } }) });
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Page<Department>>("/departments", { query: { page_size: 100 } }) });
  const enr = useQuery({
    queryKey: ["enrollments", page, status, source],
    queryFn: () => api<Page<Enrollment>>("/training/enrollments", { query: { page, page_size: 15, status, source } }),
    placeholderData: (p) => p,
  });
  return (
    <div className="space-y-4">
      <Card title="Module catalogue">
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {modules.data?.items.map((m) => (
            <li key={m.id} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <p className="font-semibold">{m.title}</p>
              <p className="text-sm text-slate-600 dark:text-slate-400">{m.description}</p>
              <p className="mt-1 text-xs">{m.lessons.length} lessons · ~{m.est_minutes} min · <Badge>{m.category}</Badge></p>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Assign training to a department">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const r = await api<{ message: string }>("/training/enrollments", { method: "POST", body: assign });
              toast.push("success", r.message);
              qc.invalidateQueries({ queryKey: ["enrollments"] });
            } catch (err) {
              toast.error(err);
            }
          }}
        >
          <Select label="Module" required value={assign.module_id} onChange={(e) => setAssign({ ...assign, module_id: e.target.value })}>
            <option value="">Choose…</option>
            {modules.data?.items.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
          </Select>
          <Select label="Department" required value={assign.department_id} onChange={(e) => setAssign({ ...assign, department_id: e.target.value })}>
            <option value="">Choose…</option>
            {depts.data?.items.map((dd) => <option key={dd.id} value={dd.id}>{dd.name}</option>)}
          </Select>
          <Button type="submit">Assign</Button>
        </form>
      </Card>
      <Card title="Enrollments">
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          <Select label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All</option><option value="enrolled">enrolled</option><option value="in_progress">in progress</option><option value="completed">completed</option>
          </Select>
          <Select label="Source" value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }}>
            <option value="">All</option><option value="auto">automatic (failed a simulation)</option><option value="manual">manual</option>
          </Select>
        </div>
        {enr.data && (
          <>
            <Table caption="Enrollments" head={["Person", "Module", "Status", "Progress", "Source"]}>
              {enr.data.items.map((e) => (
                <tr key={e.id}>
                  <td className="px-2 py-1">{e.target_name}</td>
                  <td className="px-2 py-1">{e.module_title}</td>
                  <td className="px-2 py-1"><Badge tone={STATUS_TONE[e.status]}>{e.status}</Badge></td>
                  <td className="px-2 py-1">{e.progress_pct}%</td>
                  <td className="px-2 py-1">{e.source}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={page} pageSize={15} total={enr.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <Leaderboards />
    </div>
  );
}

export default function TrainingPage() {
  const { user } = useAuth();
  const manager = atLeast(user?.role, "manager");
  return (
    <>
      <PageHeader title="Training" subtitle={manager ? "Modules, assignments and progress." : "Short lessons and quizzes. Pass the quiz to earn a certificate."} />
      {manager ? <ManagerTraining /> : <LearnerTraining />}
    </>
  );
}
