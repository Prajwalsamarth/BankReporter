// frontend/src/blocks.ts
import type { Block, BlockType } from "./api";

export const uid = (): string =>
  globalThis.crypto?.randomUUID?.() ?? `b${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;

export const BLOCK_TYPES: { value: BlockType; label: string }[] = [
  { value: "heading", label: "Heading" }, { value: "text", label: "Text" }, { value: "kpi_row", label: "KPI row" },
  { value: "table", label: "Table" }, { value: "chart", label: "Chart" }, { value: "page_break", label: "Page break" },
];

export function newBlock(type: BlockType): Block {
  const id = uid();
  switch (type) {
    case "heading": return { id, type, text: "New section", level: 2 };
    case "text": return { id, type, text: "{{client_name}} · {{period}}" };
    case "kpi_row": return { id, type, filters: [],
      items: [{ measure: { metric: "applications" } }, { measure: { metric: "approval_rate" } }] };
    case "kpi": return { id, type, measure: { metric: "applications" }, filters: [], sparkline: true };
    case "table": return { id, type, title: "New table", totals: false,
      query: { measures: [{ metric: "applications" }], group_by: ["channel"], filters: [] } };
    case "chart": return { id, type, title: "New chart", chart: "bar",
      query: { measures: [{ metric: "applications" }], group_by: ["application_month"], filters: [] } };
    case "page_break": return { id, type };
  }
}

export const cloneBlock = (b: Block): Block => ({ ...structuredClone(b), id: uid() });

export function describeBlock(b: Block): string {
  switch (b.type) {
    case "heading": return `Heading: ${b.text ?? ""}`;
    case "text": return `Text: ${(b.text ?? "").slice(0, 40)}`;
    case "kpi_row": return `KPI row (${b.items?.length ?? 0})`;
    case "kpi": return `KPI: ${b.label || b.measure?.metric || b.measure?.field || ""}`;
    case "table": return `Table: ${b.title || "untitled"}`;
    case "chart": return `Chart (${b.chart}): ${b.title || "untitled"}`;
    case "page_break": return "Page break";
  }
}
