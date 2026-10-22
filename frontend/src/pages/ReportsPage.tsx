// frontend/src/pages/ReportsPage.tsx
import { Anchor, Button, Card, Group, Loader, Select, Stack, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type PeriodSpec, type Rendered, type ReportSummary } from "../api";
import { BlockView } from "../components/BlockView";
import { useMe } from "../auth";
import { NoClient } from "../components/NoClient";
import { OwnerBadge } from "../components/OwnerBadge";
import { RenderError } from "../components/RenderError";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

export function ReportsPage() {
  const qc = useQueryClient();
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => api<ReportSummary[]>("/reports") });
  const me = useMe();
  const clientId = me.data?.client?.id ?? null;
  const [selected, setSelected] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodSpec>({ preset: "last_month" });
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (reports.data?.length && (selected === null || !reports.data.some((r) => r.id === selected))) {
      setSelected(reports.data[0].id);
    }
  }, [reports.data, selected]);

  const rendered = useQuery({
    queryKey: ["render-report", selected, clientId, period],
    enabled: selected !== null && clientId !== null && periodReady(period),
    queryFn: () => api<Rendered>(`/reports/${selected}/render`, { method: "POST", json: { period } }),
    retry: false,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`/reports/${id}`, { method: "DELETE" }),
    onSuccess: () => { setConfirming(false); setSelected(null); qc.invalidateQueries({ queryKey: ["reports"] }); },
  });
  const template = reports.data?.find((r) => r.id === selected);

  return (
    <Stack>
      <Group justify="space-between" className="no-print">
        <Title order={2}>Reports</Title>
        <Button component={Link} to="/reports/new">New template</Button>
      </Group>
      <Card withBorder className="no-print">
        <Group align="flex-end" wrap="wrap">
          <Select label="Template" w={260} allowDeselect={false} value={selected === null ? null : String(selected)}
            data={(reports.data ?? []).map((r) => ({ value: String(r.id), label: r.name }))}
            onChange={(v) => { setConfirming(false); setSelected(Number(v)); }} />
          {template && <OwnerBadge item={template} />}
          <PeriodSelect value={period} onChange={setPeriod} />
          <Button variant="default" disabled={!rendered.data} onClick={() => window.print()}>Download PDF</Button>
          {template && (template.editable ? (
            <Group gap="xs">
              <Anchor component={Link} to={`/reports/${template.id}/edit`} size="sm">Edit template</Anchor>
              {confirming ? (
                <>
                  <Button size="xs" color="red" loading={remove.isPending} onClick={() => remove.mutate(template.id)}>Confirm delete</Button>
                  <Button size="xs" variant="subtle" onClick={() => setConfirming(false)}>Cancel</Button>
                </>
              ) : (
                <Button size="xs" variant="subtle" color="red" onClick={() => setConfirming(true)}>Delete template</Button>
              )}
            </Group>
          ) : (
            <Anchor component={Link} to={`/reports/${template.id}/edit`} size="sm">Save as…</Anchor>
          ))}
        </Group>
      </Card>
      {reports.data?.length === 0 && <Text c="dimmed">No report templates yet.</Text>}
      {me.data && clientId === null && <NoClient />}
      {rendered.isError && <RenderError error={rendered.error} />}
      {rendered.isFetching && !rendered.data && <Loader />}
      {rendered.data && (
        <div className="report-paper">
          <Group justify="space-between" mb="md">
            <div>
              <Text fw={700}>{template?.name}</Text>
              <Text size="sm" c="dimmed">{rendered.data.client.name} · {rendered.data.period.label}</Text>
            </div>
            <Text size="xs" c="dimmed">Generated {rendered.data.generated_at.replace("T", " ").slice(0, 16)}</Text>
          </Group>
          {rendered.data.blocks.map((b) => <div key={b.id} className="report-block"><BlockView result={b} /></div>)}
        </div>
      )}
    </Stack>
  );
}
