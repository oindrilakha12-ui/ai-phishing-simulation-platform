"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Campaign, Department, Page, Template } from "@/lib/types";
import { Badge, Button, Input, Loading, Select, STATUS_TONE, Textarea } from "./ui";

export type CampaignFormValue = {
  name: string;
  description: string;
  template_id: string;
  department_ids: string[];
  scheduled_at: string;
};

export function toFormValue(c?: Campaign): CampaignFormValue {
  return {
    name: c?.name ?? "",
    description: c?.description ?? "",
    template_id: c?.template_id ?? "",
    department_ids: c?.department_ids ?? [],
    scheduled_at: c?.scheduled_at ? c.scheduled_at.slice(0, 16) : "",
  };
}

export function CampaignForm({ initial, onSubmit, submitLabel }: { initial: CampaignFormValue; onSubmit: (v: CampaignFormValue) => Promise<void>; submitLabel: string }) {
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const templates = useQuery({ queryKey: ["templates", "all"], queryFn: () => api<Page<Template>>("/templates", { query: { page_size: 100, sort: "name", order: "asc" } }) });
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Page<Department>>("/departments", { query: { page_size: 100 } }) });
  if (templates.isLoading || depts.isLoading) return <Loading />;
  const selected = templates.data?.items.find((t) => t.id === v.template_id);
  const toggleDept = (id: string) =>
    setV((s) => ({ ...s, department_ids: s.department_ids.includes(id) ? s.department_ids.filter((x) => x !== id) : [...s.department_ids, id] }));

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await onSubmit(v);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Input label="Name" required minLength={3} maxLength={120} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
      <Textarea label="Description" rows={2} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
      <Select label="Template (fictional brand, watermarked)" value={v.template_id} onChange={(e) => setV({ ...v, template_id: e.target.value })}>
        <option value="">— choose a template —</option>
        {(["easy", "medium", "hard"] as const).map((tier) => (
          <optgroup key={tier} label={`Difficulty: ${tier}`}>
            {templates.data?.items.filter((t) => t.difficulty === tier).map((t) => (
              <option key={t.id} value={t.id}>{t.name} ({t.brand})</option>
            ))}
          </optgroup>
        ))}
      </Select>
      {selected && (
        <p className="text-sm">
          <Badge tone={STATUS_TONE[selected.difficulty]}>{selected.difficulty}</Badge> Subject: “{selected.subject}” · {selected.red_flags.length} red flags
        </p>
      )}
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Target departments (synthetic people)</legend>
        <div className="flex flex-wrap gap-2">
          {depts.data?.items.map((d) => (
            <label key={d.id} className="flex items-center gap-2 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600">
              <input type="checkbox" checked={v.department_ids.includes(d.id)} onChange={() => toggleDept(d.id)} />
              {d.name}
            </label>
          ))}
        </div>
      </fieldset>
      <Input
        label="Scheduled start (optional)"
        type="datetime-local"
        hint="Scheduling is synthetic: at this time the campaign becomes active and in-app previews appear."
        value={v.scheduled_at}
        onChange={(e) => setV({ ...v, scheduled_at: e.target.value })}
      />
      <div>
        <Button type="submit" loading={busy}>{submitLabel}</Button>
      </div>
    </form>
  );
}

export function formToPayload(v: CampaignFormValue) {
  return {
    name: v.name,
    description: v.description,
    template_id: v.template_id || null,
    department_ids: v.department_ids,
    scheduled_at: v.scheduled_at ? new Date(v.scheduled_at).toISOString() : null,
  };
}
