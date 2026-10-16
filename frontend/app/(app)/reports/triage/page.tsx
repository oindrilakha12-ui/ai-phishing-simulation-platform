"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { IndicatorList, ScoreGauge } from "@/components/indicators";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Pagination, Select, STATUS_TONE, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { dt, titleCase } from "@/lib/format";
import type { Indicator, Page } from "@/lib/types";

type Report = {
  id: string;
  subject: string;
  status: string;
  heuristic_score: number | null;
  analysis: { indicators: Indicator[]; suggested_status?: string; verdict: string } | null;
  feedback: string | null;
  reporter: string | null;
  raw_text: string;
  matched_campaign_id: string | null;
  created_at: string;
};

function TriagePanel({ report, onDone }: { report: Report; onDone: () => void }) {
  const toast = useToast();
  const [status, setStatus] = useState(report.analysis?.suggested_status ?? "triaged");
  const [feedback, setFeedback] = useState(report.feedback ?? "");
  return (
    <Card title={report.subject}>
      <p className="mb-2 text-sm">Reported by {report.reporter} · {dt(report.created_at)}</p>
      {report.heuristic_score != null && <ScoreGauge score={report.heuristic_score} label="Heuristic suspicion score" />}
      {report.matched_campaign_id && <p className="mt-2"><Badge tone="purple">Matches an active training simulation</Badge></p>}
      <details className="my-3">
        <summary className="cursor-pointer text-sm font-medium">Raw content (displayed as plain text)</summary>
        <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{report.raw_text}</pre>
      </details>
      <h3 className="mb-2 text-sm font-semibold">Indicator Analyst findings</h3>
      <IndicatorList indicators={report.analysis?.indicators ?? []} />
      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api(`/reports/${report.id}/triage`, { method: "POST", body: { status, feedback } });
            toast.push("success", "Triaged — the reporter was notified in-app");
            onDone();
          } catch (err) {
            toast.error(err);
          }
        }}
      >
        <Select label="Decision" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="triaged">Triaged (under review)</option>
          <option value="confirmed_sim">Confirmed simulation</option>
          <option value="benign">Benign</option>
        </Select>
        <Textarea label="Feedback to reporter (in-app)" rows={3} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
        <Button type="submit">Save decision</Button>
      </form>
    </Card>
  );
}

export default function TriageQueue() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("new");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Report | null>(null);
  const q = useQuery({
    queryKey: ["triage", status, page],
    queryFn: () => api<Page<Report>>("/reports", { query: { status, page, page_size: 10 } }),
    placeholderData: (p) => p,
  });
  return (
    <>
      <PageHeader title="Triage queue" subtitle="Reports submitted by learners, pre-analysed by the deterministic Indicator Analyst." />
      <div className="mb-3 max-w-xs">
        <Select label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); setSelected(null); }}>
          <option value="">All</option>
          {["new", "triaged", "confirmed_sim", "benign"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
        </Select>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_460px]">
        <div>
          {q.isLoading && <Loading />}
          {q.error && <ErrorState error={q.error} />}
          {q.data?.items.length === 0 && <EmptyState title="Queue is empty" />}
          {q.data && q.data.items.length > 0 && (
            <>
              <Table caption="Reported emails" head={["Subject", "Reporter", "Score", "Status", "When"]}>
                {q.data.items.map((r) => (
                  <tr key={r.id} className={selected?.id === r.id ? "bg-blue-50 dark:bg-blue-950" : ""}>
                    <td className="px-2 py-1"><button className="text-left font-medium text-blue-700 hover:underline dark:text-blue-400" onClick={() => setSelected(r)}>{r.subject}</button></td>
                    <td className="px-2 py-1">{r.reporter}</td>
                    <td className="px-2 py-1">{r.heuristic_score ?? "…"}</td>
                    <td className="px-2 py-1"><Badge tone={STATUS_TONE[r.status]}>{titleCase(r.status)}</Badge></td>
                    <td className="px-2 py-1">{dt(r.created_at)}</td>
                  </tr>
                ))}
              </Table>
              <Pagination page={page} pageSize={10} total={q.data.total} onPage={setPage} />
            </>
          )}
        </div>
        <div>
          {selected ? (
            <TriagePanel key={selected.id} report={selected} onDone={() => { setSelected(null); qc.invalidateQueries({ queryKey: ["triage"] }); }} />
          ) : (
            <EmptyState title="Select a report to triage" />
          )}
        </div>
      </div>
    </>
  );
}
