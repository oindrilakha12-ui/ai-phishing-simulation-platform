"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CohortBars, DepartmentBars, FlagBars, Heatmap, TrendChart } from "@/components/charts";
import { useAuth } from "@/components/providers";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Select, Stat, TLink, Input } from "@/components/ui";
import { useToast } from "@/components/toast";
import { api, download } from "@/lib/api";
import { atLeast, dt, pct } from "@/lib/format";
import type { Campaign, Department, LiveActivityItem, Overview, Page } from "@/lib/types";

const ACTIVITY_TONE: Record<LiveActivityItem["kind"], "green" | "red" | "blue" | "amber" | "purple"> = {
  reported: "green",
  report_submitted: "purple",
  clicked_sim: "red",
  completed_training: "blue",
  previewed: "amber",
};

function LiveActivity() {
  const feed = useQuery({
    queryKey: ["live-activity"],
    queryFn: () => api<{ items: LiveActivityItem[] }>("/analytics/live-activity", { query: { limit: 8 } }),
    refetchInterval: 10_000,
  });
  return (
    <Card
      className="mb-4"
      title={<span className="flex items-center gap-2">Live activity <Badge tone="green">real users</Badge></span>}
      actions={<span className="text-xs text-slate-500">updates every 10 s</span>}
    >
      {feed.isLoading ? <Loading /> : !feed.data?.items.length ? (
        <EmptyState
          title="No real activity yet"
          hint="When a learner reports or clicks a simulation in their inbox, or submits a report, it shows up here within seconds."
        />
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {feed.data.items.map((i, idx) => (
            <li key={idx} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <Badge tone={ACTIVITY_TONE[i.kind]}>{i.label}</Badge>{" "}
                <b>{i.actor}</b>{i.department && <span className="text-slate-500"> · {i.department}</span>} — {" "}
                <TLink href={i.link}>{i.detail}</TLink>
              </span>
              <span className="text-xs text-slate-500">{dt(i.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ManagerDashboard() {
  const toast = useToast();
  const [filters, setFilters] = useState({ campaign_id: "", department_id: "", date_from: "", date_to: "", real_only: "" });
  const query = Object.fromEntries(Object.entries(filters).map(([k, v]) => [k, v || undefined]));
  const overview = useQuery({
    queryKey: ["overview", filters],
    queryFn: () => api<Overview>("/analytics/overview", { query }),
    refetchInterval: 15_000,
  });
  const realOnly = filters.real_only === "true";
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Page<Department>>("/departments", { query: { page_size: 100 } }) });
  const camps = useQuery({ queryKey: ["campaigns", "all"], queryFn: () => api<Page<Campaign>>("/campaigns", { query: { page_size: 100 } }) });

  const exportFile = (fmt: "csv" | "pdf") =>
    download(`/analytics/export.${fmt}`, `phishguard-analytics.${fmt}`, query).catch(toast.error);

  return (
    <>
      <PageHeader
        title="Analytics dashboard"
        subtitle={
          realOnly
            ? <>Showing only what <b>real logged-in users</b> did in their inbox.</>
            : <>Figures combine <b>synthetic</b> simulated employees with real user activity. Choose &quot;Real users only&quot; to see just real actions.</>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => exportFile("csv")}>Export CSV</Button>
            <Button variant="secondary" onClick={() => exportFile("pdf")}>Export PDF</Button>
          </>
        }
      />
      <LiveActivity />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Select label="Data" value={filters.real_only} onChange={(e) => setFilters({ ...filters, real_only: e.target.value })}>
            <option value="">All (synthetic + real)</option>
            <option value="true">Real users only</option>
          </Select>
          <Select label="Campaign" value={filters.campaign_id} onChange={(e) => setFilters({ ...filters, campaign_id: e.target.value })}>
            <option value="">All campaigns</option>
            {camps.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <Select label="Department" value={filters.department_id} onChange={(e) => setFilters({ ...filters, department_id: e.target.value })}>
            <option value="">All departments</option>
            {depts.data?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          <Input label="From" type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} />
          <Input label="To" type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} />
        </div>
      </Card>
      {overview.isLoading && <Loading />}
      {overview.error && <ErrorState error={overview.error} onRetry={() => overview.refetch()} />}
      {overview.data && overview.data.kpis.recipients === 0 && (
        <EmptyState
          title={realOnly ? "No real-user data yet" : "No simulation data for these filters"}
          hint={realOnly ? "Launch a campaign that includes a department with learner accounts, then act on it from the learner inbox." : "Launch a campaign or widen the date range."}
        />
      )}
      {overview.data && overview.data.kpis.recipients > 0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Recipients" value={overview.data.kpis.recipients} hint="in-app previews" />
            <Stat label="Click rate" value={pct(overview.data.kpis.click_rate)} hint={`${overview.data.kpis.clicked} ${realOnly ? "real" : "simulated"} clicks`} />
            <Stat label="Report rate" value={pct(overview.data.kpis.report_rate)} hint={`${overview.data.kpis.reported} reports`} />
            <Stat label="Report : click" value={overview.data.kpis.report_to_click_ratio ?? "—"} hint="higher is better" />
            <Stat label="Training completion" value={pct(overview.data.kpis.completion_rate)} hint={`${overview.data.kpis.enrollments} enrollments`} />
            <Stat
              label="Time to report"
              value={overview.data.kpis.time_to_report_median_min != null ? `${Math.round(overview.data.kpis.time_to_report_median_min)} min` : "—"}
              hint={`median · p90 ${overview.data.kpis.time_to_report_p90_min ?? "—"} min`}
            />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Trend (weekly)"><TrendChart data={overview.data.trend} /></Card>
            <Card title="Departments"><DepartmentBars data={overview.data.departments} /></Card>
            <Card title="Department heatmap (click rate by month)"><Heatmap data={overview.data.heatmap} /></Card>
            <Card title="Most-missed red-flag categories"><FlagBars data={overview.data.top_failed_flags} /></Card>
            <Card title="Cohort comparison (template difficulty)"><CohortBars data={overview.data.cohorts} /></Card>
          </div>
        </div>
      )}
    </>
  );
}

type Enrollment = { id: string; module_title: string; status: string; progress_pct: number; source: string };
type Badges = { points: number; streak_days: number; badges: { id: string; label: string; earned: boolean }[] };
type InboxItem = { campaign_id: string; name: string; subject: string; actions: string[] };

function LearnerDashboard() {
  const { user } = useAuth();
  const training = useQuery({ queryKey: ["my-training"], queryFn: () => api<Enrollment[]>("/training/my") });
  const badges = useQuery({ queryKey: ["badges"], queryFn: () => api<Badges>("/training/badges/me") });
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<InboxItem[]>("/inbox") });
  const pending = inbox.data?.filter((i) => !i.actions.some((a) => a === "reported" || a === "clicked_sim")) ?? [];
  const todo = training.data?.filter((e) => e.status !== "completed") ?? [];
  return (
    <>
      <PageHeader title={`Welcome, ${user?.full_name}`} subtitle="Practise spotting phishing safely. Every simulation here is an in-app preview." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Simulations to review" value={pending.length} />
        <Stat label="Training to finish" value={todo.length} />
        <Stat label="Points" value={badges.data?.points ?? "—"} />
        <Stat label="Quiz streak" value={`${badges.data?.streak_days ?? 0} days`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Simulation inbox" actions={<TLink href="/inbox">Open inbox</TLink>}>
          {inbox.isLoading ? <Loading /> : pending.length === 0 ? <EmptyState title="All caught up" /> : (
            <ul className="space-y-2 text-sm">
              {pending.slice(0, 5).map((i) => (
                <li key={i.campaign_id}><TLink href={`/inbox/${i.campaign_id}`}>{i.subject}</TLink></li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="My training" actions={<TLink href="/training">All training</TLink>}>
          {training.isLoading ? <Loading /> : todo.length === 0 ? <EmptyState title="No open training" hint="Nice work!" /> : (
            <ul className="space-y-2 text-sm">
              {todo.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2">
                  <TLink href={`/training/${e.id}`}>{e.module_title}</TLink>
                  <span className="flex gap-2">{e.source === "auto" && <Badge tone="amber">assigned</Badge>}<Badge>{e.progress_pct}%</Badge></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Badges">
          <ul className="flex flex-wrap gap-2">
            {badges.data?.badges.map((b) => (
              <li key={b.id}><Badge tone={b.earned ? "green" : "slate"}>{b.earned ? "🏅 " : ""}{b.label}</Badge></li>
            ))}
          </ul>
        </Card>
        <Card title="Personal tips" actions={<TLink href="/ai?tab=coach">Ask the Awareness Coach</TLink>}>
          <p className="text-sm text-slate-600 dark:text-slate-400">Get three microlearning tips tailored to your (synthetic) history.</p>
        </Card>
      </div>
    </>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  return atLeast(user?.role, "manager") ? <ManagerDashboard /> : <LearnerDashboard />;
}
