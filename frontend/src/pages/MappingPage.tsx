import { Alert, Badge, Button, Card, Group, Loader, Modal, ScrollArea, Select, Stack, Table, Text, Title, Tooltip } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  ApiError, api, errorText, type Catalog, type ColumnInfo, type ColumnRef, type Connection, type Entry, type JoinPlan,
  type Preview, type Published, type RunDetail,
} from "../api";
import { FieldTable, type FieldActions } from "../components/FieldTable";
import { JoinPlanCard } from "../components/JoinPlanCard";

const statusColor = { running: "blue", ready: "teal", failed: "red", published: "violet" } as const;

function counts(entries: Entry[]) {
  const mapped = entries.filter((e) => e.source && e.status !== "not_available");
  const required = entries.filter((e) => e.required);
  const by = (k: Entry["decided_by"]) => mapped.filter((e) => e.decided_by === k).length;
  return {
    summary: `Mapped ${mapped.length}/${entries.length} · Required ${required.filter((e) => e.source && e.status !== "not_available").length}/${required.length}`,
    layers: `A ${by("A")} · B ${by("B")} · C ${by("C")} · key ${by("key")} · user ${by("user")} · none ${entries.length - mapped.length}`,
  };
}

function ColumnSearchModal({ connectionId, entry, onClose, onChoose }: {
  connectionId: string; entry: Entry | null; onClose: () => void; onChoose: (ref: ColumnRef) => void;
}) {
  const [value, setValue] = useState<string | null>(null);
  const columns = useQuery({
    queryKey: ["columns", connectionId], enabled: entry !== null,
    queryFn: () => api<ColumnInfo[]>(`/connections/${connectionId}/columns`),
  });
  const key = (c: ColumnInfo) => `${c.schema ?? ""}|${c.table}|${c.column}`;
  return (
    <Modal opened={entry !== null} onClose={onClose} title={`Choose a column for ${entry?.label ?? ""}`}>
      <Stack>
        <Select searchable label="Column" value={value} onChange={setValue} nothingFoundMessage="No columns"
          data={(columns.data ?? []).map((c) => ({ value: key(c), label: `${c.table}.${c.column} (${c.type})` }))} />
        <Group justify="flex-end">
          <Button disabled={!value} onClick={() => {
            const [schema, table, column] = value!.split("|");
            onChoose({ schema: schema || null, table, column });
            setValue(null);
          }}>Use column</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function MappingPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [published, setPublished] = useState<Published | null>(null);
  const [searching, setSearching] = useState<Entry | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);

  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<Catalog>("/catalog") });
  const connection = useQuery({
    queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections"),
    select: (cs) => cs.find((c) => String(c.id) === id),
  });
  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => api<RunDetail>(`/connections/${id}/mapping-runs/latest`),
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 2,
    refetchInterval: (q) => (q.state.data?.run.status === "running" ? 2000 : false),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["run", id] });
  const onError = (err: unknown) => setActionError(errorText(err));
  const rid = run.data?.run.id;

  const start = useMutation({
    mutationFn: () => api(`/connections/${id}/mapping-runs`, { method: "POST", json: { layers: "ABC" } }),
    onSuccess: () => { setPublished(null); refresh(); }, onError,
  });
  const patch = useMutation({
    mutationFn: ({ fieldId, body }: { fieldId: string; body: object }) =>
      api(`/mapping-runs/${rid}/entries/${fieldId}`, { method: "PATCH", json: body }),
    onSuccess: () => { setActionError(null); refresh(); }, onError,
  });
  const acceptAbove = useMutation({
    mutationFn: () => api(`/mapping-runs/${rid}/accept-above`, { method: "POST", json: { threshold: 0.9 } }),
    onSuccess: refresh, onError,
  });
  const confirmPlan = useMutation({
    mutationFn: (plan: JoinPlan) => api(`/mapping-runs/${rid}/join-plan`, { method: "PUT", json: { join_plan: plan, confirmed: true } }),
    onSuccess: () => { setActionError(null); refresh(); }, onError,
  });
  const loadPreview = useMutation({
    mutationFn: () => api<Preview>(`/mapping-runs/${rid}/preview?limit=20`), onSuccess: setPreview, onError,
  });
  const publish = useMutation({
    mutationFn: () => api<Published>(`/mapping-runs/${rid}/publish`, { method: "POST" }),
    onSuccess: (p) => { setActionError(null); setPublished(p); refresh(); }, onError,
  });

  const actions: FieldActions = {
    accept: (e) => patch.mutate({ fieldId: e.field_id, body: { action: "accept" } }),
    choose: (e, ref) => patch.mutate({ fieldId: e.field_id, body: { action: "choose", schema: ref.schema, table: ref.table, column: ref.column } }),
    notAvailable: (e) => patch.mutate({ fieldId: e.field_id, body: { action: "not_available" } }),
    reset: (e) => patch.mutate({ fieldId: e.field_id, body: { action: "reset" } }),
    searchAll: setSearching,
  };

  const noRuns = run.error instanceof ApiError && run.error.status === 404;
  const detail = run.data;
  const blocked = (detail?.blockers.length ?? 1) > 0;

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{connection.data?.name ?? "Mapping"}</Title>
          {detail && (
            <Group gap="xs">
              <Text size="sm" c="dimmed">Run #{detail.run.id}</Text>
              <Badge color={statusColor[detail.run.status]}>{detail.run.status}</Badge>
              {detail.run.status !== "running" && <Text size="sm">{counts(detail.entries).summary}</Text>}
              {detail.run.status !== "running" && <Text size="sm" c="dimmed">{counts(detail.entries).layers}</Text>}
            </Group>
          )}
        </div>
        {detail && (
          <Group gap="xs">
            <Button variant="default" onClick={() => start.mutate()} loading={start.isPending}>Re-run</Button>
            <Button variant="default" onClick={() => acceptAbove.mutate()} loading={acceptAbove.isPending}
              disabled={detail.run.status === "running"}>Accept all ≥ 0.90</Button>
            <Button variant="default" onClick={() => loadPreview.mutate()} loading={loadPreview.isPending}
              disabled={detail.run.status === "running"}>Preview</Button>
            <Tooltip disabled={!blocked} multiline w={320}
              label={<Stack gap={2}>{detail.blockers.map((b) => <Text key={b} size="xs">{b}</Text>)}</Stack>}>
              <span><Button disabled={blocked} onClick={() => publish.mutate()} loading={publish.isPending}>Publish</Button></span>
            </Tooltip>
          </Group>
        )}
      </Group>

      {actionError && <Alert color="red" withCloseButton onClose={() => setActionError(null)}>{actionError}</Alert>}
      {published && (
        <Alert color="teal">Published {published.row_count} rows to {published.schema}.applications</Alert>
      )}
      {run.isLoading && <Loader />}
      {noRuns && (
        <Card withBorder>
          <Stack align="flex-start">
            <Text>No mapping runs yet for this connection.</Text>
            <Button onClick={() => start.mutate()} loading={start.isPending}>Run mapping</Button>
          </Stack>
        </Card>
      )}
      {detail?.run.status === "running" && (
        <Alert color="blue" icon={<Loader size="xs" />}>Mapping in progress: profiling columns and matching fields…</Alert>
      )}
      {detail?.run.error && <Alert color="red">Run failed: {detail.run.error}</Alert>}
      {detail?.run.warnings.includes("llm_disabled") && (
        <Alert color="yellow">
          LLM layer off: OPENAI_API_KEY is not set, so Layer C was skipped and low-confidence columns use the embedding match.
        </Alert>
      )}

      {detail && detail.join_plan && detail.run.status !== "running" && (
        <JoinPlanCard key={detail.run.id} plan={detail.join_plan} confirmed={detail.run.join_plan_confirmed}
          saving={confirmPlan.isPending} onConfirm={(p) => confirmPlan.mutate(p)} />
      )}
      {detail && detail.affected_calculated.length > 0 && (
        <Card withBorder>
          <Text fw={600} size="sm">Calculated fields that will always be empty</Text>
          <Text size="sm" ff="monospace">{detail.affected_calculated.join(", ")}</Text>
        </Card>
      )}
      {detail && catalog.data && detail.entries.length > 0 && (
        <FieldTable entries={detail.entries} sections={catalog.data.sections} actions={actions} />
      )}

      <ColumnSearchModal connectionId={id} entry={searching} onClose={() => setSearching(null)}
        onChoose={(ref) => { if (searching) actions.choose(searching, ref); setSearching(null); }} />
      <Modal opened={preview !== null} onClose={() => setPreview(null)} title="Preview (first 20 rows)" size="90%">
        <ScrollArea>
          <Table striped withTableBorder fz="xs">
            <Table.Thead><Table.Tr>{preview?.columns.map((c) => <Table.Th key={c}>{c}</Table.Th>)}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {preview?.rows.map((r, i) => (
                <Table.Tr key={i}>{r.map((v, j) => <Table.Td key={j}>{v === null ? "" : String(v)}</Table.Td>)}</Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Modal>
    </Stack>
  );
}
