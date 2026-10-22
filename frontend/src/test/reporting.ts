// frontend/src/test/reporting.ts
import type { BlockResult, CatalogField, Kpi, Metric } from "../api";

export const kpi = (over: Partial<Kpi> = {}): Kpi => ({
  key: "approval_rate", label: "Approval rate", unit: "pct",
  value: { raw: 61.2, display: "61.2%" }, previous: { raw: 59.1, display: "59.1%" },
  delta: { raw: 2.1, display: "+2.1 pts", direction: "up", good: true }, ...over,
});

export const FIELDS: CatalogField[] = [
  { id: "channel", label: "Sourcing Channel", section: "application", kind: "raw", type: "enum", role: "dimension",
    values: ["BRANCH", "DSA", "WEB"], unit: null },
  { id: "application_month", label: "Application Month", section: "application", kind: "calculated", type: "date",
    role: "dimension", values: null, unit: null },
  { id: "disbursed_amount", label: "Disbursed Amount", section: "disbursement", kind: "raw", type: "decimal",
    role: "measure", values: null, unit: "INR" },
  { id: "cibil_score", label: "CIBIL Score", section: "bureau", kind: "raw", type: "integer", role: "measure",
    values: null, unit: null },
];

export const METRICS: Metric[] = [
  { id: "applications", label: "Applications", unit: "count", better: "higher", group: "volume", description: "" },
  { id: "approval_rate", label: "Approval rate", unit: "pct", better: "higher", group: "rates", description: "" },
];

/** A render-blocks mock: echoes each requested block back as a heading result. */
export const echoRender = (_url: string, init?: RequestInit) => {
  const { blocks } = JSON.parse(String(init!.body)) as { blocks: { id: string }[] };
  return {
    client: { id: 7, name: "NovaBank" },
    period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
    generated_at: "2026-10-22T18:05:00",
    blocks: blocks.map((b): BlockResult => ({ id: b.id, type: "heading", text: `rendered ${b.id}`, level: 2 })),
  };
};
