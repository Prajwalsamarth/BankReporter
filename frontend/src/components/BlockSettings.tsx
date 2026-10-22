// frontend/src/components/BlockSettings.tsx
import {
  ActionIcon, Button, Group, MultiSelect, NumberInput, Select, Stack, Switch, TagsInput, Text, TextInput, Textarea,
} from "@mantine/core";
import type { Agg, Block, CatalogField, ChartType, Filter, Measure, Metric, QuerySpec } from "../api";

const GROUPS: [string, string][] = [["volume", "Volume"], ["rates", "Rates"], ["amounts", "Amounts"],
                                    ["credit", "Credit"], ["turnaround", "Turnaround"]];
const AGG_LABELS: Record<Agg, string> = { count: "Count", count_distinct: "Count distinct", sum: "Sum",
                                          avg: "Average", min: "Minimum", max: "Maximum" };
const CHARTS: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Bar" }, { value: "stacked_bar", label: "Stacked bar" }, { value: "line", label: "Line" },
  { value: "area", label: "Area" }, { value: "pie", label: "Pie" },
];
const OPS = [
  { value: "eq", label: "=" }, { value: "ne", label: "≠" }, { value: "in", label: "is one of" },
  { value: "not_in", label: "is not one of" }, { value: "gt", label: ">" }, { value: "gte", label: "≥" },
  { value: "lt", label: "<" }, { value: "lte", label: "≤" }, { value: "is_null", label: "is empty" },
  { value: "not_null", label: "is not empty" },
];
const LIST_OPS = new Set(["in", "not_in"]);
const NULL_OPS = new Set(["is_null", "not_null"]);

interface Common { fields: CatalogField[]; metrics: Metric[] }

/** The first library metric not already used, so new measures never duplicate an existing one. */
function unusedMetric(metrics: Metric[], used: Measure[]): string {
  const taken = new Set(used.map((m) => m.metric));
  return (metrics.find((m) => !taken.has(m.id)) ?? metrics[0]).id;
}

function defaultValue(f: CatalogField | undefined): unknown {
  if (!f) return "";
  if (f.type === "enum") return f.values?.[0] ?? "";
  if (f.type === "boolean") return true;
  if (f.type === "integer" || f.type === "decimal") return 0;
  return "";
}

function MeasurePicker({ value, onChange, fields, metrics, label }: Common & {
  value: Measure; onChange: (m: Measure) => void; label: string;
}) {
  const data = [
    ...GROUPS.map(([g, name]) => ({ group: name, items: metrics.filter((m) => m.group === g)
      .map((m) => ({ value: `m:${m.id}`, label: m.label })) })).filter((g) => g.items.length > 0),
    { group: "Other", items: [{ value: "field", label: "Field aggregate…" }] },
  ];
  const field = fields.find((f) => f.id === value.field);
  const aggs: Agg[] = field?.role === "measure" ? ["sum", "avg", "min", "max", "count", "count_distinct"] : ["count", "count_distinct"];
  return (
    <Stack gap={4}>
      <Select label={label} data={data} searchable allowDeselect={false}
        value={value.metric ? `m:${value.metric}` : "field"}
        onChange={(v) => onChange(v === "field"
          ? { field: fields.find((f) => f.role === "measure")?.id ?? fields[0].id, agg: "sum" }
          : { metric: v!.slice(2) })} />
      {!value.metric && (
        <Group grow>
          <Select label="Field" searchable allowDeselect={false} value={value.field ?? null}
            data={fields.map((f) => ({ value: f.id, label: f.label }))}
            onChange={(v) => {
              const f = fields.find((x) => x.id === v)!;
              onChange({ field: f.id, agg: f.role === "measure" ? (value.agg ?? "sum") : "count" });
            }} />
          <Select label="Aggregate" allowDeselect={false} value={value.agg ?? null}
            data={aggs.map((a) => ({ value: a, label: AGG_LABELS[a] }))}
            onChange={(v) => onChange({ ...value, agg: v as Agg })} />
        </Group>
      )}
    </Stack>
  );
}

function ValueInput({ field, op, value, onChange, index }: {
  field: CatalogField | undefined; op: string; value: unknown; onChange: (v: unknown) => void; index: number;
}) {
  const label = `Filter ${index} value`;
  if (!field || NULL_OPS.has(op)) return null;
  const list = LIST_OPS.has(op);
  if (field.type === "enum") {
    const data = field.values ?? [];
    return list
      ? <MultiSelect aria-label={label} data={data} value={(value as string[]) ?? []} onChange={onChange} />
      : <Select aria-label={label} data={data} value={(value as string) ?? null} allowDeselect={false} onChange={onChange} />;
  }
  if (field.type === "boolean") {
    return <Select aria-label={label} allowDeselect={false} data={[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]}
      value={String(value ?? true)} onChange={(v) => onChange(v === "true")} />;
  }
  if (field.type === "integer" || field.type === "decimal") {
    return list
      ? <TagsInput aria-label={label} value={((value as number[]) ?? []).map(String)}
          onChange={(vs) => onChange(vs.map(Number).filter((n) => !Number.isNaN(n)))} />
      : <NumberInput aria-label={label} value={(value as number) ?? 0}
          onChange={(n) => onChange(typeof n === "number" ? n : Number(n))} />;
  }
  return list
    ? <TagsInput aria-label={label} value={(value as string[]) ?? []} onChange={onChange} />
    : <TextInput aria-label={label} value={(value as string) ?? ""} placeholder={field.type === "date" ? "YYYY-MM-DD" : undefined}
        onChange={(e) => onChange(e.currentTarget.value)} />;
}

function FiltersEditor({ filters, onChange, fields }: { filters: Filter[]; onChange: (f: Filter[]) => void; fields: CatalogField[] }) {
  const update = (i: number, f: Filter) => onChange(filters.map((x, j) => (j === i ? f : x)));
  const first = fields.find((f) => f.id === "channel") ?? fields[0];
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>Filters</Text>
      {filters.map(([fieldId, op, value], i) => {
        const field = fields.find((f) => f.id === fieldId);
        return (
          <Group key={i} gap="xs" align="flex-end" wrap="nowrap">
            <Select aria-label={`Filter ${i + 1} field`} searchable allowDeselect={false} w={150} value={fieldId}
              data={fields.map((f) => ({ value: f.id, label: f.label }))}
              onChange={(v) => { const f = fields.find((x) => x.id === v); update(i, [v!, "eq", defaultValue(f)]); }} />
            <Select aria-label={`Filter ${i + 1} operator`} allowDeselect={false} w={120} data={OPS} value={op}
              onChange={(next) => {
                const o = next!;
                if (NULL_OPS.has(o)) return update(i, [fieldId, o]);
                const v = LIST_OPS.has(o) ? (Array.isArray(value) ? value : [value ?? defaultValue(field)])
                                          : (Array.isArray(value) ? value[0] : value ?? defaultValue(field));
                update(i, [fieldId, o, v]);
              }} />
            <ValueInput field={field} op={op} value={value} index={i + 1} onChange={(v) => update(i, [fieldId, op, v])} />
            <ActionIcon variant="subtle" color="red" aria-label={`Remove filter ${i + 1}`}
              onClick={() => onChange(filters.filter((_, j) => j !== i))}>✕</ActionIcon>
          </Group>
        );
      })}
      <Button size="xs" variant="light" w="fit-content"
        onClick={() => onChange([...filters, [first.id, "eq", defaultValue(first)]])}>Add filter</Button>
    </Stack>
  );
}

function QueryEditor({ query, onChange, fields, metrics, chart }: Common & {
  query: QuerySpec; onChange: (q: QuerySpec) => void; chart?: ChartType;
}) {
  const set = (patch: Partial<QuerySpec>) => onChange({ ...query, ...patch });
  // De-duplicated: Mantine Select throws on duplicate option values, which would blank the whole page.
  const keys = [...new Set([...query.measures.map((m) => m.metric ?? `${m.agg}_${m.field}`), ...query.group_by])];
  const dims = fields.filter((f) => f.role === "dimension");
  return (
    <Stack gap="sm">
      {query.measures.map((m, i) => (
        <Group key={i} align="flex-end" wrap="nowrap" gap="xs">
          <div style={{ flex: 1 }}>
            <MeasurePicker label={`Measure ${i + 1}`} value={m} fields={fields} metrics={metrics}
              onChange={(nm) => set({ measures: query.measures.map((x, j) => (j === i ? nm : x)) })} />
          </div>
          {query.measures.length > 1 && (
            <ActionIcon variant="subtle" color="red" aria-label={`Remove measure ${i + 1}`}
              onClick={() => set({ measures: query.measures.filter((_, j) => j !== i) })}>✕</ActionIcon>
          )}
        </Group>
      ))}
      <Button size="xs" variant="light" w="fit-content" disabled={query.measures.length >= 4 || chart === "pie"}
        onClick={() => set({ measures: [...query.measures, { metric: unusedMetric(metrics, query.measures) }] })}>Add measure</Button>
      <MultiSelect label="Group by" maxValues={2} searchable value={query.group_by}
        data={dims.map((f) => ({ value: f.id, label: f.label }))} onChange={(v) => set({ group_by: v })} />
      <FiltersEditor filters={query.filters} fields={fields} onChange={(f) => set({ filters: f })} />
      <Group grow>
        <Select label="Sort by" clearable value={query.sort?.by ?? null} data={keys}
          onChange={(v) => set({ sort: v ? { by: v, dir: query.sort?.dir ?? "desc" } : null })} />
        <Select label="Direction" allowDeselect={false} disabled={!query.sort} value={query.sort?.dir ?? "desc"}
          data={[{ value: "desc", label: "Descending" }, { value: "asc", label: "Ascending" }]}
          onChange={(v) => query.sort && set({ sort: { ...query.sort, dir: v as "asc" | "desc" } })} />
        <NumberInput label="Limit" min={1} max={500} value={query.limit ?? ""}
          onChange={(n) => set({ limit: typeof n === "number" ? n : null })} />
      </Group>
    </Stack>
  );
}

export function BlockSettings({ block, onChange, fields, metrics }: Common & { block: Block; onChange: (b: Block) => void }) {
  const set = (patch: Partial<Block>) => onChange({ ...block, ...patch });
  switch (block.type) {
    case "heading":
      return (
        <Stack>
          <TextInput label="Text" value={block.text ?? ""} onChange={(e) => set({ text: e.currentTarget.value })} />
          <Select label="Level" allowDeselect={false} data={["1", "2", "3"]} value={String(block.level ?? 1)}
            onChange={(v) => set({ level: Number(v) })} />
        </Stack>
      );
    case "text":
      return (
        <Textarea label="Text" autosize minRows={4} value={block.text ?? ""}
          description="Placeholders: {{client_name}} {{period}} {{period_start}} {{period_end}} {{generated_at}} {{metric:approval_rate}}"
          onChange={(e) => set({ text: e.currentTarget.value })} />
      );
    case "kpi_row": {
      const items = block.items ?? [];
      return (
        <Stack>
          <TextInput label="Title" value={block.title ?? ""} onChange={(e) => set({ title: e.currentTarget.value || null })} />
          {items.map((it, i) => (
            <Group key={i} align="flex-end" wrap="nowrap" gap="xs">
              <div style={{ flex: 1 }}>
                <MeasurePicker label={`KPI ${i + 1}`} value={it.measure} fields={fields} metrics={metrics}
                  onChange={(m) => set({ items: items.map((x, j) => (j === i ? { ...x, measure: m } : x)) })} />
              </div>
              <ActionIcon variant="subtle" color="red" aria-label={`Remove KPI ${i + 1}`} disabled={items.length === 1}
                onClick={() => set({ items: items.filter((_, j) => j !== i) })}>✕</ActionIcon>
            </Group>
          ))}
          <Button size="xs" variant="light" w="fit-content" disabled={items.length >= 6}
            onClick={() => set({ items: [...items, { measure: { metric: unusedMetric(metrics, items.map((i) => i.measure)) } }] })}>Add KPI</Button>
          <FiltersEditor filters={block.filters ?? []} fields={fields} onChange={(f) => set({ filters: f })} />
        </Stack>
      );
    }
    case "kpi":
      return (
        <Stack>
          <MeasurePicker label="Measure" value={block.measure ?? { metric: metrics[0].id }} fields={fields} metrics={metrics}
            onChange={(m) => set({ measure: m })} />
          <TextInput label="Label" placeholder="Default label" value={block.label ?? ""}
            onChange={(e) => set({ label: e.currentTarget.value || null })} />
          <Switch label="Show 6-month sparkline" checked={block.sparkline ?? true}
            onChange={(e) => set({ sparkline: e.currentTarget.checked })} />
          <FiltersEditor filters={block.filters ?? []} fields={fields} onChange={(f) => set({ filters: f })} />
        </Stack>
      );
    case "table":
    case "chart":
      return (
        <Stack>
          <TextInput label="Title" value={block.title ?? ""} onChange={(e) => set({ title: e.currentTarget.value || null })} />
          {block.type === "chart" && (
            <Select label="Chart type" allowDeselect={false} data={CHARTS} value={block.chart ?? "bar"}
              onChange={(v) => set({ chart: v as ChartType })} />
          )}
          {block.type === "table" && (
            <Switch label="Totals row" checked={block.totals ?? false} onChange={(e) => set({ totals: e.currentTarget.checked })} />
          )}
          <QueryEditor query={block.query!} fields={fields} metrics={metrics} chart={block.chart}
            onChange={(q) => set({ query: q })} />
        </Stack>
      );
    case "page_break":
      return <Text c="dimmed" size="sm">Starts a new page when the report is printed.</Text>;
  }
}
