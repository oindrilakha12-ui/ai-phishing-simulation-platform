"use client";
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState, ErrorState, Loading, PageHeader, Table, TLink } from "@/components/ui";
import { api } from "@/lib/api";
import { dt } from "@/lib/format";

type Item = { campaign_id: string; name: string; subject: string; sender_name: string; started_at: string; actions: string[] };

export default function InboxPage() {
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => api<Item[]>("/inbox") });
  return (
    <>
      <PageHeader title="Simulation inbox" subtitle="Training simulations appear here, never in your real mailbox. Open one and decide: report it, or (if you're fooled) open the link." />
      {q.isLoading && <Loading />}
      {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data?.length === 0 && <EmptyState title="No simulations yet" />}
      {q.data && q.data.length > 0 && (
        <Table caption="Simulations" head={["From", "Subject", "Received", "Outcome"]}>
          {q.data.map((i) => (
            <tr key={i.campaign_id}>
              <td className="px-2 py-2">{i.sender_name}</td>
              <td className="px-2 py-2"><TLink href={`/inbox/${i.campaign_id}`}>{i.subject}</TLink></td>
              <td className="px-2 py-2">{dt(i.started_at)}</td>
              <td className="px-2 py-2">
                {i.actions.includes("reported") ? <Badge tone="green">Reported ✓</Badge> : i.actions.includes("clicked_sim") ? <Badge tone="red">Clicked</Badge> : <Badge tone="blue">Unreviewed</Badge>}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
