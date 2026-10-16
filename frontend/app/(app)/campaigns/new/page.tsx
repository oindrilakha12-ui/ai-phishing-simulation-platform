"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { CampaignForm, formToPayload, toFormValue } from "@/components/campaign-form";
import { useToast } from "@/components/toast";
import { Card, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { Campaign } from "@/lib/types";

export default function NewCampaign() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  return (
    <>
      <PageHeader title="New campaign" subtitle="Campaigns start as drafts. Launching generates in-app previews and synthetic outcomes only." />
      <Card>
        <CampaignForm
          initial={toFormValue()}
          submitLabel="Create draft"
          onSubmit={async (v) => {
            try {
              const c = await api<Campaign>("/campaigns", { method: "POST", body: formToPayload(v) });
              qc.invalidateQueries({ queryKey: ["campaigns"] });
              toast.push("success", "Draft created");
              router.push(`/campaigns/${c.id}`);
            } catch (e) {
              toast.error(e);
            }
          }}
        />
      </Card>
    </>
  );
}
