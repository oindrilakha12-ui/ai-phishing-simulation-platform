"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, Input, Loading, PageHeader, STATUS_TONE, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { dt, titleCase } from "@/lib/format";
import type { Page } from "@/lib/types";

type Report = { id: string; subject: string; status: string; heuristic_score: number | null; feedback: string | null; created_at: string };

export default function ReportPhish() {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ subject: "", raw_text: "" });
  const [busy, setBusy] = useState(false);
  const mine = useQuery({ queryKey: ["my-reports"], queryFn: () => api<Page<Report>>("/reports/mine", { query: { page_size: 20 } }) });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/reports", { method: "POST", body: form });
      toast.push("success", "Thanks for reporting! A manager will review it — watch the 🔔 bell for the result.");
      setForm({ subject: "", raw_text: "" });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["my-reports"] }), 500);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Report a suspicious email" subtitle="Paste the email (headers help!). Don't forward it to colleagues and don't click anything in it." />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="New report">
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Input label="Subject" required maxLength={300} value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            <Textarea
              label="Email content (paste raw source if you can)"
              hint="In most mail apps: More (…) → View source / Show original. Max 50 KB."
              rows={10}
              required
              minLength={10}
              maxLength={50000}
              value={form.raw_text}
              onChange={(e) => setForm({ ...form, raw_text: e.target.value })}
            />
            <Button type="submit" loading={busy}>Submit report</Button>
          </form>
        </Card>
        <Card title="My reports">
          {mine.isLoading && <Loading />}
          {mine.data?.items.length === 0 && <EmptyState title="You haven't reported anything yet" />}
          {mine.data && mine.data.items.length > 0 && (
            <Table caption="My reports" head={["Subject", "Status", "Feedback", "When"]}>
              {mine.data.items.map((r) => (
                <tr key={r.id}>
                  <td className="px-2 py-1">{r.subject}</td>
                  <td className="px-2 py-1"><Badge tone={STATUS_TONE[r.status]}>{titleCase(r.status)}</Badge></td>
                  <td className="px-2 py-1 text-sm">{r.feedback ?? "—"}</td>
                  <td className="px-2 py-1">{dt(r.created_at)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
