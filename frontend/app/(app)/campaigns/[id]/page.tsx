"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { CampaignForm, formToPayload, toFormValue } from "@/components/campaign-form";
import { PreviewSandbox } from "@/components/preview-sandbox";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorState, Loading, PageHeader, Pagination, Stat, STATUS_TONE, Table, TLink } from "@/components/ui";
import { api } from "@/lib/api";
import { dt, pct, titleCase } from "@/lib/format";
import type { Campaign, Page, Preview } from "@/lib/types";

const NEXT_STEPS: Record<string, { to: string; label: string; variant?: "danger" | "secondary" }[]> = {
  draft: [{ to: "scheduled", label: "Schedule" }, { to: "active", label: "Launch now" }],
  scheduled: [{ to: "active", label: "Launch now" }, { to: "draft", label: "Back to draft", variant: "secondary" }],
  active: [{ to: "completed", label: "Complete campaign" }],
  completed: [],
};

type Event = { id: string; target_name: string; event_type: string; occurred_at: string; red_flag_category: string | null; is_synthetic: boolean };

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [evPage, setEvPage] = useState(1);
  const c = useQuery({ queryKey: ["campaign", id], queryFn: () => api<Campaign>(`/campaigns/${id}`) });
  const preview = useQuery({
    queryKey: ["preview", c.data?.template_id],
    queryFn: () => api<Preview>(`/templates/${c.data!.template_id}/preview`),
    enabled: !!c.data?.template_id,
  });
  const events = useQuery({
    queryKey: ["campaign-events", id, evPage],
    queryFn: () => api<Page<Event>>(`/campaigns/${id}/events`, { query: { page: evPage, page_size: 10 } }),
    enabled: !!c.data && c.data.status !== "draft",
  });

  if (c.isLoading) return <Loading />;
  if (c.error) return <ErrorState error={c.error} onRetry={() => c.refetch()} />;
  const camp = c.data!;

  const transition = async (to: string) => {
    try {
      await api(`/campaigns/${id}/transition`, { method: "POST", body: { to } });
      toast.push("success", to === "active" ? "Launched — synthetic previews generated" : `Moved to ${to}`);
      // Synthetic events are generated right after the response; refresh shortly after.
      setTimeout(() => qc.invalidateQueries(), 600);
      qc.invalidateQueries({ queryKey: ["campaign", id] });
    } catch (e) {
      toast.error(e);
    }
  };
  const remove = async () => {
    if (!confirm("Delete this campaign? (soft delete)")) return;
    try {
      await api(`/campaigns/${id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      router.push("/campaigns");
    } catch (e) {
      toast.error(e);
    }
  };

  return (
    <>
      <PageHeader
        title={camp.name}
        subtitle={<><Badge tone={STATUS_TONE[camp.status]}>{camp.status}</Badge> <span className="ml-2">{camp.description}</span></>}
        actions={
          <>
            {NEXT_STEPS[camp.status].map((s) => (
              <Button key={s.to} variant={s.variant ?? "primary"} onClick={() => transition(s.to)}>{s.label}</Button>
            ))}
            {(camp.status === "draft" || camp.status === "scheduled") && (
              <Button variant="secondary" onClick={() => setEditing((e) => !e)}>{editing ? "Cancel edit" : "Edit"}</Button>
            )}
            {camp.status !== "active" && <Button variant="danger" onClick={remove}>Delete</Button>}
          </>
        }
      />
      <ol aria-label="Lifecycle" className="mb-4 flex flex-wrap gap-2 text-sm">
        {["draft", "scheduled", "active", "completed"].map((s) => (
          <li key={s} aria-current={camp.status === s ? "step" : undefined}>
            <Badge tone={camp.status === s ? STATUS_TONE[s] : "slate"}>{camp.status === s ? "● " : ""}{s}</Badge>
          </li>
        ))}
      </ol>
      {editing && (
        <Card className="mb-4" title="Edit campaign">
          <CampaignForm
            initial={toFormValue(camp)}
            submitLabel="Save changes"
            onSubmit={async (v) => {
              try {
                await api(`/campaigns/${id}`, { method: "PATCH", body: formToPayload(v) });
                setEditing(false);
                qc.invalidateQueries({ queryKey: ["campaign", id] });
                toast.push("success", "Saved");
              } catch (e) {
                toast.error(e);
              }
            }}
          />
        </Card>
      )}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Recipients" value={camp.stats?.recipients ?? 0} />
        <Stat label="Click rate" value={pct(camp.stats?.click_rate)} />
        <Stat label="Report rate" value={pct(camp.stats?.report_rate)} />
        <Stat label="Report : click" value={camp.stats?.report_to_click_ratio ?? "—"} />
        <Stat label="Completed training" value={camp.stats?.completed_training ?? 0} />
      </div>
      <Card className="mb-4" title="Details">
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="font-medium">Template</dt><dd>{camp.template_id ? <TLink href={`/templates/${camp.template_id}`}>{camp.template_name}</TLink> : "—"}</dd></div>
          <div><dt className="font-medium">Departments</dt><dd>{camp.department_names.join(", ") || "—"}</dd></div>
          <div><dt className="font-medium">Scheduled</dt><dd>{dt(camp.scheduled_at)}</dd></div>
          <div><dt className="font-medium">Started / completed</dt><dd>{dt(camp.started_at)} / {dt(camp.completed_at)}</dd></div>
        </dl>
      </Card>
      {preview.data && (
        <Card className="mb-4" title="Lure preview (sandboxed)">
          <PreviewSandbox preview={preview.data} height={360} />
        </Card>
      )}
      {events.data && (
        <Card title="Synthetic event log">
          <Table caption="Simulation events" head={["When", "Person", "Event", "Red flag missed", "Source"]}>
            {events.data.items.map((e) => (
              <tr key={e.id}>
                <td className="px-2 py-1">{dt(e.occurred_at)}</td>
                <td className="px-2 py-1">{e.target_name}</td>
                <td className="px-2 py-1"><Badge tone={e.event_type === "clicked_sim" ? "red" : e.event_type === "reported" ? "blue" : "slate"}>{titleCase(e.event_type)}</Badge></td>
                <td className="px-2 py-1">{e.red_flag_category ? titleCase(e.red_flag_category) : "—"}</td>
                <td className="px-2 py-1">{e.is_synthetic ? "synthetic" : "learner action"}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={evPage} pageSize={10} total={events.data.total} onPage={setEvPage} />
        </Card>
      )}
    </>
  );
}
