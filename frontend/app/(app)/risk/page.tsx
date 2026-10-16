"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorState, Loading, PageHeader, Pagination, Select, STATUS_TONE, Table } from "@/components/ui";
import { api, download } from "@/lib/api";
import type { Page } from "@/lib/types";

type DeptRisk = { department_id: string; department: string; score: number; level: string; people: number; high_risk_people: number };
type Factor = { key: string; label: string; impact: number; detail: string };
type TargetRisk = { target_id: string; name: string; department_id: string; score: number; level: string; factors: Factor[] };

const COLORS = ["#1d4ed8", "#b91c1c", "#047857", "#b45309", "#7c3aed", "#0f766e", "#be185d"];

export default function RiskPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [level, setLevel] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const depts = useQuery({ queryKey: ["risk-depts"], queryFn: () => api<{ current: DeptRisk[]; history: Record<string, { at: string; score: number }[]> }>("/risk/departments") });
  const people = useQuery({
    queryKey: ["risk-people", page, level],
    queryFn: () => api<Page<TargetRisk>>("/risk/targets", { query: { page, page_size: 12, level, sort: "score", order: "desc" } }),
    placeholderData: (p) => p,
  });

  // Reshape history into one row per date with a column per department.
  const chartRows = (() => {
    if (!depts.data) return [];
    const byDate: Record<string, Record<string, number | string>> = {};
    for (const d of depts.data.current) {
      for (const h of depts.data.history[d.department_id] ?? []) {
        const key = h.at.slice(0, 10);
        byDate[key] ??= { date: key };
        byDate[key][d.department] = h.score;
      }
    }
    return Object.values(byDate).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  })();

  return (
    <>
      <PageHeader
        title="Risk & reports"
        subtitle="Explainable 0–100 risk scores computed from synthetic outcomes and training completion."
        actions={
          <>
            <Button variant="secondary" onClick={() => download("/risk/export.csv", "phishguard-risk.csv").catch(toast.error)}>Risk CSV</Button>
            <Button variant="secondary" onClick={() => download("/analytics/export.pdf", "phishguard-compliance-report.pdf").catch(toast.error)}>Compliance PDF</Button>
            <Button
              onClick={async () => {
                try {
                  const r = await api<{ message: string }>("/risk/recompute", { method: "POST" });
                  toast.push("success", r.message);
                  qc.invalidateQueries({ queryKey: ["risk-depts"] });
                  qc.invalidateQueries({ queryKey: ["risk-people"] });
                } catch (e) {
                  toast.error(e);
                }
              }}
            >
              Record snapshot
            </Button>
          </>
        }
      />
      {depts.isLoading && <Loading />}
      {depts.error && <ErrorState error={depts.error} />}
      {depts.data && (
        <div className="mb-4 grid gap-4 xl:grid-cols-2">
          <Card title="Department risk (current)">
            <Table caption="Department risk" head={["Department", "Score", "Level", "People", "High-risk"]}>
              {depts.data.current.map((d) => (
                <tr key={d.department_id}>
                  <td className="px-2 py-1">{d.department}</td>
                  <td className="px-2 py-1 font-semibold">{d.score}</td>
                  <td className="px-2 py-1"><Badge tone={STATUS_TONE[d.level]}>{d.level}</Badge></td>
                  <td className="px-2 py-1">{d.people}</td>
                  <td className="px-2 py-1">{d.high_risk_people}</td>
                </tr>
              ))}
            </Table>
          </Card>
          <Card title="Department risk trend (weekly snapshots)">
            <div className="h-72" aria-label="Line chart of department risk over time; the table on the left has current values">
              <ResponsiveContainer>
                <LineChart data={chartRows} margin={{ left: -15 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {depts.data.current.map((d, i) => (
                    <Line key={d.department_id} dataKey={d.department} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={2} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      )}
      <Card title="People (synthetic) by risk">
        <div className="mb-3 max-w-xs">
          <Select label="Level" value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }}>
            <option value="">All</option><option>high</option><option>medium</option><option>low</option>
          </Select>
        </div>
        {people.data && (
          <>
            <Table caption="People by risk" head={["Name", "Score", "Level", "Why"]}>
              {people.data.items.map((p) => (
                <tr key={p.target_id} className="align-top">
                  <td className="px-2 py-1">{p.name}</td>
                  <td className="px-2 py-1 font-semibold">{p.score}</td>
                  <td className="px-2 py-1"><Badge tone={STATUS_TONE[p.level]}>{p.level}</Badge></td>
                  <td className="px-2 py-1">
                    <button className="text-sm text-blue-700 hover:underline dark:text-blue-400" aria-expanded={open === p.target_id} onClick={() => setOpen(open === p.target_id ? null : p.target_id)}>
                      {open === p.target_id ? "Hide factors" : "Explain"}
                    </button>
                    {open === p.target_id && (
                      <ul className="mt-1 space-y-0.5 text-xs">
                        {p.factors.map((f) => (
                          <li key={f.key}>
                            <span className={f.impact > 0 ? "text-red-700 dark:text-red-400" : "text-green-700 dark:text-green-400"}>{f.impact > 0 ? "+" : ""}{f.impact}</span> {f.label} — {f.detail}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
            <Pagination page={page} pageSize={12} total={people.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
