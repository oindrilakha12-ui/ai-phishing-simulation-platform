"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { PreviewSandbox } from "@/components/preview-sandbox";
import { useToast } from "@/components/toast";
import { Button, Card, ErrorState, Loading, PageHeader, TLink } from "@/components/ui";
import { api } from "@/lib/api";
import type { Preview, RedFlag } from "@/lib/types";

type ActionResult = { recorded: boolean; red_flags: RedFlag[]; landing_page?: string; enrolled_module?: string | null; message?: string };

export default function InboxItem() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const [result, setResult] = useState<ActionResult | null>(null);
  const preview = useQuery({ queryKey: ["inbox-preview", id], queryFn: () => api<Preview>(`/inbox/${id}/preview`) });

  const act = async (action: "reported" | "clicked_sim") => {
    try {
      const r = await api<ActionResult>(`/inbox/${id}/action`, { method: "POST", body: { action } });
      setResult(r);
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["my-training"] });
    } catch (e) {
      toast.error(e);
    }
  };

  if (preview.isLoading) return <Loading />;
  if (preview.error) return <ErrorState error={preview.error} />;
  const p = preview.data!;
  const shown: Preview = result?.landing_page ? { ...p, document: result.landing_page, links: [] } : p;

  return (
    <>
      <PageHeader title="Review this message" subtitle="Would you trust it? Use the buttons below — nothing leaves the app." />
      {!result && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Button onClick={() => act("reported")}>🚩 Report phish</Button>
          <Button variant="secondary" onClick={() => act("clicked_sim")}>Open the link (simulated)</Button>
        </div>
      )}
      {result?.message && <Card className="mb-4"><p role="status" className="font-medium text-green-800 dark:text-green-300">{result.message}</p></Card>}
      {result?.landing_page && (
        <Card className="mb-4">
          <p role="status" className="font-medium text-amber-900 dark:text-amber-200">
            This was a simulation. No data was collected. {result.enrolled_module && <>You&apos;ve been enrolled in <TLink href="/training">{result.enrolled_module}</TLink>.</>}
          </p>
        </Card>
      )}
      <Card>
        <PreviewSandbox preview={shown} flags={result ? result.red_flags : []} />
      </Card>
    </>
  );
}
