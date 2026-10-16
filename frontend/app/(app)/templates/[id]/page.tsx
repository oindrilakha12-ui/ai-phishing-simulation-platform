"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { PreviewSandbox } from "@/components/preview-sandbox";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorState, Loading, PageHeader, STATUS_TONE, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { dt } from "@/lib/format";
import type { Preview, Template } from "@/lib/types";

type Version = { id: string; version: number; changed_by: string | null; created_at: string; snapshot: Partial<Template> };

export default function TemplateDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const tmpl = useQuery({ queryKey: ["template", id], queryFn: () => api<Template>(`/templates/${id}`) });
  const preview = useQuery({ queryKey: ["preview", id], queryFn: () => api<Preview>(`/templates/${id}/preview`) });
  const versions = useQuery({ queryKey: ["versions", id], queryFn: () => api<Version[]>(`/templates/${id}/versions`) });

  if (tmpl.isLoading || preview.isLoading) return <Loading />;
  if (tmpl.error) return <ErrorState error={tmpl.error} />;
  const t = tmpl.data!;
  return (
    <>
      <PageHeader
        title={t.name}
        subtitle={<><Badge tone={STATUS_TONE[t.difficulty] ?? "amber"}>{t.difficulty}</Badge> <span className="ml-2">{t.brand} · v{t.version} · {t.category}</span></>}
        actions={
          <Button
            variant="danger"
            onClick={async () => {
              if (!confirm("Delete this template? (soft delete)")) return;
              try {
                await api(`/templates/${id}`, { method: "DELETE" });
                qc.invalidateQueries({ queryKey: ["templates"] });
                router.push("/templates");
              } catch (e) {
                toast.error(e);
              }
            }}
          >
            Delete
          </Button>
        }
      />
      {preview.data && (
        <Card className="mb-4" title="Preview sandbox">
          <PreviewSandbox preview={preview.data} />
        </Card>
      )}
      <Card title="Version history">
        {versions.data && (
          <Table caption="Template versions" head={["Version", "When", "Subject at that version"]}>
            {versions.data.map((v) => (
              <tr key={v.id}>
                <td className="px-2 py-1">v{v.version}</td>
                <td className="px-2 py-1">{dt(v.created_at)}</td>
                <td className="px-2 py-1">{v.snapshot.subject}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
