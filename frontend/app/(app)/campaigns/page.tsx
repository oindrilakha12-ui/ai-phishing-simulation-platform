"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, EmptyState, ErrorState, Input, Loading, PageHeader, Pagination, Select, STATUS_TONE, Table, TLink } from "@/components/ui";
import { api } from "@/lib/api";
import { d, pct } from "@/lib/format";
import type { Campaign, Page } from "@/lib/types";

export default function CampaignsPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("created_at");
  const query = useQuery({
    queryKey: ["campaigns", page, status, q, sort],
    queryFn: () => api<Page<Campaign>>("/campaigns", { query: { page, page_size: 10, status, q, sort, order: sort === "name" ? "asc" : "desc" } }),
    placeholderData: (prev) => prev,
  });
  return (
    <>
      <PageHeader
        title="Campaigns"
        subtitle="Simulations are delivered as in-app previews to synthetic learners. Nothing is emailed."
        actions={<Link href="/campaigns/new" className="rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white hover:bg-blue-800">New campaign</Link>}
      />
      <div className="mb-3 grid gap-3 sm:grid-cols-3">
        <Input label="Search" placeholder="Name or description" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All</option>
          {["draft", "scheduled", "active", "completed"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <Select label="Sort by" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="created_at">Newest</option>
          <option value="started_at">Start date</option>
          <option value="name">Name</option>
          <option value="status">Status</option>
        </Select>
      </div>
      {query.isLoading && <Loading />}
      {query.error && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.data && query.data.items.length === 0 && <EmptyState title="No campaigns match" action={<TLink href="/campaigns/new">Create one</TLink>} />}
      {query.data && query.data.items.length > 0 && (
        <>
          <Table caption="Campaigns" head={["Name", "Status", "Template", "Departments", "Started", "Click", "Report"]}>
            {query.data.items.map((c) => (
              <tr key={c.id}>
                <td className="px-2 py-2"><TLink href={`/campaigns/${c.id}`}>{c.name}</TLink></td>
                <td className="px-2 py-2"><Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge></td>
                <td className="px-2 py-2">{c.template_name ?? "—"} {c.template_difficulty && <Badge tone={STATUS_TONE[c.template_difficulty] ?? "slate"}>{c.template_difficulty}</Badge>}</td>
                <td className="px-2 py-2">{c.department_names.join(", ") || "—"}</td>
                <td className="px-2 py-2">{d(c.started_at ?? c.scheduled_at)}</td>
                <td className="px-2 py-2">{c.stats?.recipients ? pct(c.stats.click_rate) : "—"}</td>
                <td className="px-2 py-2">{c.stats?.recipients ? pct(c.stats.report_rate) : "—"}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pageSize={10} total={query.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
