// frontend/src/components/BlockView.tsx
import { Alert, Badge, Card, Divider, Group, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { AreaChart, BarChart, LineChart, PieChart, Sparkline } from "@mantine/charts";
import type { BlockResult, Delta, Kpi } from "../api";

const PALETTE = ["blue.6", "teal.6", "orange.6", "grape.6", "red.6", "cyan.6", "lime.6", "pink.6", "indigo.6", "yellow.6"];
const deltaColor = (d: Delta) => (d.good === null ? "gray" : d.good ? "teal" : "red");
const arrow = { up: "▲", down: "▼", flat: "■" } as const;
const indian = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function Empty() {
  return <Text c="dimmed" size="sm" py="md" ta="center">No applications in this period</Text>;
}

export function KpiCard({ kpi }: { kpi: Kpi }) {
  return (
    <Card withBorder padding="sm" h="100%">
      <Text size="xs" c="dimmed">{kpi.label}</Text>
      <Text fw={700} fz={26}>{kpi.value.display}</Text>
      <Group gap="xs">
        {kpi.delta && (
          <Badge variant="light" color={deltaColor(kpi.delta)} data-good={String(kpi.delta.good)}>
            {arrow[kpi.delta.direction]} {kpi.delta.display}
          </Badge>
        )}
        <Text size="xs" c="dimmed">prev {kpi.previous.display}</Text>
      </Group>
      {kpi.sparkline && kpi.sparkline.length > 1 && (
        <Sparkline mt="xs" h={36} data={kpi.sparkline.map((p) => p.raw ?? 0)} curveType="linear" color="blue" />
      )}
    </Card>
  );
}

function TableView({ result }: { result: BlockResult }) {
  const cols = result.columns ?? [];
  return (
    <Stack gap={4}>
      {result.title && <Text fw={600}>{result.title}</Text>}
      {result.empty ? <Empty /> : (
        <Table striped withTableBorder fz="sm">
          <Table.Thead><Table.Tr>
            {cols.map((c) => <Table.Th key={c.key} ta={c.kind === "measure" ? "right" : undefined}>{c.label}</Table.Th>)}
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {(result.rows ?? []).map((r, i) => (
              <Table.Tr key={i}>
                {cols.map((c) => <Table.Td key={c.key} ta={c.kind === "measure" ? "right" : undefined}>{r[c.key]?.display}</Table.Td>)}
              </Table.Tr>
            ))}
            {result.totals && (
              <Table.Tr fw={700}>
                {cols.map((c, i) => (
                  <Table.Td key={c.key} ta={c.kind === "measure" ? "right" : undefined}>
                    {c.kind === "measure" ? result.totals![c.key]?.display : i === 0 ? "Total" : ""}
                  </Table.Td>
                ))}
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function ChartView({ result }: { result: BlockResult }) {
  const cols = result.columns ?? [];
  const dims = cols.filter((c) => c.kind === "dimension");
  const measures = cols.filter((c) => c.kind === "measure");
  const rows = result.rows ?? [];
  const num = (v: unknown) => (typeof v === "number" ? v : v === null || v === undefined ? 0 : Number(v));
  let chart = null;
  if (result.chart === "pie") {
    const data = rows.map((r, i) => ({ name: r[dims[0].key].display, value: num(r[measures[0].key].raw),
                                       color: PALETTE[i % PALETTE.length] }));
    chart = <PieChart h={260} data={data} withLabels withTooltip labelsType="percent" />;
  } else {
    let data: Record<string, string | number>[];
    let series: { name: string; label?: string; color: string }[];
    if (dims.length === 2) {   // pivot: x = first dimension, one series per second-dimension value
      const names = [...new Set(rows.map((r) => r[dims[1].key].display))];
      const byX = new Map<string, Record<string, string | number>>();
      for (const r of rows) {
        const x = r[dims[0].key].display;
        const point = byX.get(x) ?? { x };
        point[r[dims[1].key].display] = num(r[measures[0].key].raw);
        byX.set(x, point);
      }
      data = [...byX.values()];
      series = names.map((n, i) => ({ name: n, color: PALETTE[i % PALETTE.length] }));
    } else {
      data = rows.map((r) => ({ x: r[dims[0].key].display,
        ...Object.fromEntries(measures.map((m) => [m.key, num(r[m.key].raw)])) }));
      series = measures.map((m, i) => ({ name: m.key, label: m.label, color: PALETTE[i % PALETTE.length] }));
    }
    const common = { h: 260, data, dataKey: "x", series, valueFormatter: (v: number) => indian.format(v), withLegend: series.length > 1 };
    chart = result.chart === "line" ? <LineChart {...common} curveType="linear" />
      : result.chart === "area" ? <AreaChart {...common} curveType="linear" />
      : <BarChart {...common} type={result.chart === "stacked_bar" ? "stacked" : "default"} />;
  }
  return (
    <Stack gap={4}>
      {result.title && <Text fw={600}>{result.title}</Text>}
      {result.empty ? <Empty /> : chart}
    </Stack>
  );
}

export function BlockView({ result }: { result: BlockResult }) {
  if (result.error) {
    return <Alert color="red" title="This block could not be rendered">{result.error}</Alert>;
  }
  switch (result.type) {
    case "heading":
      return <Title order={((result.level ?? 1) + 1) as 2 | 3 | 4}>{result.text}</Title>;
    case "text":
      return <Text style={{ whiteSpace: "pre-wrap" }}>{result.text}</Text>;
    case "kpi_row":
      return (
        <Stack gap={4}>
          {result.title && <Text fw={600}>{result.title}</Text>}
          <SimpleGrid cols={{ base: 1, sm: Math.min(result.items?.length ?? 1, 3), md: result.items?.length ?? 1 }}>
            {(result.items ?? []).map((k) => <KpiCard key={k.key} kpi={k} />)}
          </SimpleGrid>
        </Stack>
      );
    case "kpi":
      return result.kpi ? <KpiCard kpi={result.kpi} /> : null;
    case "table":
      return <TableView result={result} />;
    case "chart":
      return <ChartView result={result} />;
    case "page_break":
      return <div className="page-break"><Divider className="screen-only" label="Page break" labelPosition="center" /></div>;
  }
}
