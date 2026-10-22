// frontend/src/pages/ReportEditorPage.tsx
import { ActionIcon, Alert, Badge, Button, Card, Grid, Group, Loader, Menu, Stack, Text, TextInput, UnstyledButton } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError, api, errorText, type Block, type BlockType, type Catalog, type Metric, type PeriodSpec, type Rendered,
  type ReportTemplate,
} from "../api";
import { BLOCK_TYPES, cloneBlock, describeBlock, newBlock } from "../blocks";
import { BlockSettings } from "../components/BlockSettings";
import { BlockView } from "../components/BlockView";
import { ClientSelect } from "../components/ClientSelect";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

interface Draft { name: string; description: string; blocks: Block[] }

export function ReportEditorPage() {
  const { id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<Catalog>("/catalog") });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metric[]>("/metrics") });
  const existing = useQuery({ queryKey: ["report", id], enabled: !isNew, queryFn: () => api<ReportTemplate>(`/reports/${id}`) });

  const [draft, setDraft] = useState<Draft | null>(isNew ? { name: "Untitled report", description: "", blocks: [] } : null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [client, setClient] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodSpec>({ preset: "last_month" });
  const [blockErrors, setBlockErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<{ color: string; text: string } | null>(null);

  useEffect(() => {
    if (existing.data && draft === null) {
      const { name, description, blocks } = existing.data;
      setDraft({ name, description, blocks });
    }
  }, [existing.data, draft]);

  const [debounced] = useDebouncedValue(draft?.blocks ?? [], 600);
  const preview = useQuery({
    queryKey: ["render-blocks", debounced, client, period],
    enabled: client !== null && debounced.length > 0 && periodReady(period),
    queryFn: () => api<Rendered>("/render-blocks", { method: "POST", json: { blocks: debounced, connection_id: client, period } }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => (isNew
      ? api<ReportTemplate>("/reports", { method: "POST", json: draft })
      : api<ReportTemplate>(`/reports/${id}`, { method: "PUT", json: draft })),
    onSuccess: (t) => {
      setDirty(false);
      setBlockErrors({});
      setMessage({ color: "teal", text: "Saved" });
      qc.invalidateQueries({ queryKey: ["reports"] });
      if (isNew) navigate(`/reports/${t.id}/edit`, { replace: true });
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? (err.detail as { errors?: { block_id: string; messages: string[] }[] }) : null;
      setBlockErrors(Object.fromEntries((detail?.errors ?? []).map((e) => [e.block_id, e.messages])));
      setMessage({ color: "red", text: errorText(err) });
    },
  });

  if (!draft || !catalog.data || !metrics.data) return <Loader />;
  const blocks = draft.blocks;
  const update = (patch: Partial<Draft>) => { setDraft({ ...draft, ...patch }); setDirty(true); };
  const setBlocks = (next: Block[]) => update({ blocks: next });
  const move = (i: number, d: number) => { const next = [...blocks]; const [b] = next.splice(i, 1); next.splice(i + d, 0, b); setBlocks(next); };
  const add = (type: BlockType) => { const b = newBlock(type); setBlocks([...blocks, b]); setSelectedId(b.id); };
  const selected = blocks.find((b) => b.id === selectedId) ?? null;
  const results = new Map((preview.data?.blocks ?? []).map((r) => [r.id, r]));

  return (
    <Stack>
      {leaving && (
        <Alert color="yellow" title="Discard unsaved changes?">
          <Group gap="xs" mt="xs">
            <Button size="xs" color="red" onClick={() => navigate("/reports")}>Discard changes</Button>
            <Button size="xs" variant="default" onClick={() => setLeaving(false)}>Keep editing</Button>
          </Group>
        </Alert>
      )}
      <Group align="flex-end" wrap="wrap">
        <TextInput label="Template name" w={260} value={draft.name} onChange={(e) => update({ name: e.currentTarget.value })} />
        <TextInput label="Description" w={320} value={draft.description} onChange={(e) => update({ description: e.currentTarget.value })} />
        <ClientSelect label="Preview client" value={client} onChange={setClient} />
        <PeriodSelect value={period} onChange={setPeriod} />
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
        <Button variant="default" onClick={() => (dirty ? setLeaving(true) : navigate("/reports"))}>Back to reports</Button>
        {dirty && <Badge color="orange" variant="light">Unsaved changes</Badge>}
      </Group>
      {message && <Alert color={message.color} withCloseButton onClose={() => setMessage(null)}>{message.text}</Alert>}

      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Stack gap="xs" data-testid="block-list">
            <Menu>
              <Menu.Target><Button variant="light">Add block</Button></Menu.Target>
              <Menu.Dropdown>
                {BLOCK_TYPES.map((t) => <Menu.Item key={t.value} onClick={() => add(t.value)}>{t.label}</Menu.Item>)}
              </Menu.Dropdown>
            </Menu>
            {blocks.map((b, i) => (
              <Card key={b.id} withBorder padding="xs" data-testid="block-item"
                bg={b.id === selectedId ? "var(--mantine-color-blue-light)" : undefined}>
                <UnstyledButton onClick={() => setSelectedId(b.id)} w="100%">
                  <Text size="sm" truncate>{describeBlock(b)}</Text>
                </UnstyledButton>
                {blockErrors[b.id] && <Text size="xs" c="red">{blockErrors[b.id].join("; ")}</Text>}
                <Group gap={2} mt={4}>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Move block ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Move block ${i + 1} down`} disabled={i === blocks.length - 1} onClick={() => move(i, 1)}>↓</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" aria-label={`Duplicate block ${i + 1}`}
                    onClick={() => setBlocks([...blocks.slice(0, i + 1), cloneBlock(b), ...blocks.slice(i + 1)])}>⧉</ActionIcon>
                  <ActionIcon size="sm" variant="subtle" color="red" aria-label={`Delete block ${i + 1}`}
                    onClick={() => setBlocks(blocks.filter((x) => x.id !== b.id))}>✕</ActionIcon>
                </Group>
              </Card>
            ))}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <div className="report-paper">
            {client === null && <Text c="dimmed" size="sm">Choose a preview client to see live data.</Text>}
            {preview.isError && <Alert color="red">{errorText(preview.error)}</Alert>}
            {blocks.map((b) => (
              <div key={b.id} className="report-block">
                {results.get(b.id) ? <BlockView result={results.get(b.id)!} /> : <Text c="dimmed" size="sm">{describeBlock(b)}</Text>}
              </div>
            ))}
          </div>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 3 }}>
          {selected ? (
            <BlockSettings block={selected} fields={catalog.data.fields} metrics={metrics.data}
              onChange={(nb) => setBlocks(blocks.map((b) => (b.id === nb.id ? nb : b)))} />
          ) : (
            <Text c="dimmed" size="sm">Select a block to edit its settings.</Text>
          )}
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
