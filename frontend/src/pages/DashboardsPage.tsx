// frontend/src/pages/DashboardsPage.tsx
import { ActionIcon, Alert, Button, Card, Drawer, Group, Loader, Menu, Select, Stack, TextInput, Title } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api, errorText, type Catalog, type Dashboard, type DashboardSummary, type Metric, type PeriodSpec, type Rendered, type Tile,
} from "../api";
import { cloneBlock, newBlock, uid } from "../blocks";
import { BlockSettings } from "../components/BlockSettings";
import { BlockView } from "../components/BlockView";
import { useMe } from "../auth";
import { NoClient } from "../components/NoClient";
import { OwnerBadge } from "../components/OwnerBadge";
import { RenderError } from "../components/RenderError";
import { SharingChoice } from "../components/SharingChoice";
import { PeriodSelect, periodReady } from "../components/PeriodSelect";

const HEIGHT = { s: 120, m: 260, l: 380 } as const;
const WIDTHS = ["3", "4", "6", "8", "12"];
const TILE_TYPES = [{ value: "kpi", label: "KPI" }, { value: "chart", label: "Chart" }, { value: "table", label: "Table" }] as const;

export function DashboardsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["dashboards"], queryFn: () => api<DashboardSummary[]>("/dashboards") });
  const board = useQuery({ queryKey: ["dashboard", id], enabled: !!id, queryFn: () => api<Dashboard>(`/dashboards/${id}`) });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<Catalog>("/catalog") });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metric[]>("/metrics") });

  const me = useMe();
  const clientId = me.data?.client?.id ?? null;
  const [shared, setShared] = useState(true);
  const [period, setPeriod] = useState<PeriodSpec | null>(null);
  const [editing, setEditing] = useState(false);
  const [tiles, setTiles] = useState<Tile[] | null>(null);      // working copy once edited
  const [editingTile, setEditingTile] = useState<string | null>(null);
  const [saveAsName, setSaveAsName] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!id && list.data?.length) navigate(`/dashboards/${list.data[0].id}`, { replace: true });
  }, [id, list.data, navigate]);
  useEffect(() => {
    if (board.data) { setPeriod(board.data.default_period); setTiles(null); setEditing(false); }
  }, [board.data?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const shown = tiles ?? board.data?.tiles ?? [];
  const [debounced] = useDebouncedValue(shown, 400);
  const rendered = useQuery({
    queryKey: ["render-dashboard", id, tiles === null ? "saved" : debounced, clientId, period],
    enabled: !!id && clientId !== null && periodReady(period) && shown.length > 0,
    queryFn: () => (tiles === null
      ? api<Rendered>(`/dashboards/${id}/render`, { method: "POST", json: { period } })
      : api<Rendered>("/render-blocks", { method: "POST", json: { blocks: debounced.map((t) => t.block), period } })),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const body = () => ({ name: board.data!.name, default_period: period ?? board.data!.default_period, tiles: shown });
  const save = useMutation({
    mutationFn: () => api<Dashboard>(`/dashboards/${id}`, { method: "PUT", json: body() }),
    onSuccess: () => { setTiles(null); setEditing(false); setMessage(null); qc.invalidateQueries({ queryKey: ["dashboard", id] }); },
    onError: (e) => setMessage(errorText(e)),
  });
  const saveAs = useMutation({
    mutationFn: (name: string) => api<Dashboard>("/dashboards", { method: "POST", json: { ...body(), name, shared } }),
    onSuccess: (d) => { setSaveAsName(null); qc.invalidateQueries({ queryKey: ["dashboards"] }); navigate(`/dashboards/${d.id}`); },
    onError: (e) => setMessage(errorText(e)),
  });

  if (list.data?.length === 0) return <Alert color="yellow">No dashboards yet.</Alert>;
  if (!board.data || !catalog.data || !metrics.data || !period) return <Loader />;

  const update = (next: Tile[]) => setTiles(next);
  const patchTile = (i: number, patch: Partial<Tile>) => update(shown.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const move = (i: number, d: number) => { const next = [...shown]; const [t] = next.splice(i, 1); next.splice(i + d, 0, t); update(next); };
  const results = new Map((rendered.data?.blocks ?? []).map((r) => [r.id, r]));
  const tileBeingEdited = shown.find((t) => t.id === editingTile);

  return (
    <Stack>
      <Group align="flex-end" wrap="wrap">
        <Title order={2} mr="md">Dashboards</Title>
        <Select label="Dashboard" w={220} allowDeselect={false} value={id ?? null}
          data={(list.data ?? []).map((d) => ({ value: String(d.id), label: d.name }))}
          onChange={(v) => navigate(`/dashboards/${v}`)} />
        <OwnerBadge item={board.data} />
        <PeriodSelect value={period} onChange={setPeriod} />
        <Button variant="default" onClick={() => rendered.refetch()}>Refresh</Button>
        {board.data.editable && (
          <Button variant={editing ? "filled" : "default"} onClick={() => setEditing((e) => !e)}>{editing ? "Done" : "Edit"}</Button>
        )}
        {tiles !== null && <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>}
        {saveAsName === null ? (
          <Button variant="subtle" onClick={() => setSaveAsName(`${board.data!.name} (copy)`)}>
            {board.data.editable ? "Save as…" : "Save as copy"}
          </Button>
        ) : (
          <Group gap="xs" align="flex-end">
            <TextInput label="New dashboard name" value={saveAsName} onChange={(e) => setSaveAsName(e.currentTarget.value)} />
            <SharingChoice shared={shared} onChange={setShared} />
            <Button onClick={() => saveAs.mutate(saveAsName)} loading={saveAs.isPending}>Create</Button>
            <Button variant="subtle" onClick={() => setSaveAsName(null)}>Cancel</Button>
          </Group>
        )}
      </Group>
      {message && <Alert color="red" withCloseButton onClose={() => setMessage(null)}>{message}</Alert>}
      {me.data && clientId === null && <NoClient />}
      {rendered.isError && <RenderError error={rendered.error} />}
      {editing && (
        <Menu>
          <Menu.Target><Button variant="light" w="fit-content">Add tile</Button></Menu.Target>
          <Menu.Dropdown>
            {TILE_TYPES.map((t) => (
              <Menu.Item key={t.value} onClick={() => update([...shown, { id: uid(), block: newBlock(t.value),
                width: t.value === "kpi" ? 3 : 6, height: t.value === "kpi" ? "m" : "l" }])}>{t.label}</Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))", gap: 12 }}>
        {shown.map((t, i) => (
          <Card key={t.id} withBorder padding="sm" style={{ gridColumn: `span ${t.width}`, minHeight: HEIGHT[t.height] }}>
            {editing && (
              <Group gap={4} mb="xs" wrap="wrap">
                <Select aria-label={`Width of tile ${i + 1}`} w={70} size="xs" allowDeselect={false} data={WIDTHS}
                  value={String(t.width)} onChange={(v) => patchTile(i, { width: Number(v) as Tile["width"] })} />
                <Select aria-label={`Height of tile ${i + 1}`} w={70} size="xs" allowDeselect={false} data={["s", "m", "l"]}
                  value={t.height} onChange={(v) => patchTile(i, { height: v as Tile["height"] })} />
                <ActionIcon size="sm" variant="subtle" aria-label={`Edit tile ${i + 1}`} onClick={() => setEditingTile(t.id)}>✎</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Move tile ${i + 1} earlier`} disabled={i === 0} onClick={() => move(i, -1)}>←</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Move tile ${i + 1} later`} disabled={i === shown.length - 1} onClick={() => move(i, 1)}>→</ActionIcon>
                <ActionIcon size="sm" variant="subtle" aria-label={`Duplicate tile ${i + 1}`}
                  onClick={() => update([...shown.slice(0, i + 1), { ...t, id: uid(), block: cloneBlock(t.block) }, ...shown.slice(i + 1)])}>⧉</ActionIcon>
                <ActionIcon size="sm" variant="subtle" color="red" aria-label={`Delete tile ${i + 1}`}
                  onClick={() => update(shown.filter((x) => x.id !== t.id))}>✕</ActionIcon>
              </Group>
            )}
            {results.get(t.block.id) ? <BlockView result={results.get(t.block.id)!} /> : <Loader size="sm" />}
          </Card>
        ))}
      </div>
      <Drawer opened={!!tileBeingEdited} onClose={() => setEditingTile(null)} position="right" size="md" title="Tile settings">
        {tileBeingEdited && (
          <BlockSettings block={tileBeingEdited.block} fields={catalog.data.fields} metrics={metrics.data}
            onChange={(b) => update(shown.map((t) => (t.id === tileBeingEdited.id ? { ...t, block: b } : t)))} />
        )}
      </Drawer>
    </Stack>
  );
}
