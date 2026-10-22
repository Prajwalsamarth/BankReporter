export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`/api${path}`, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText);
  return body as T;
}

export type Dialect = "postgresql" | "mysql";

export interface Connection {
  id: number;
  name: string;
  dialect: Dialect;
  url_masked: string | null;
  schemas: string[];
  needs_password: boolean;
}

export interface ConnectionInput {
  name: string;
  dialect: Dialect;
  host: string;
  port: number;
  database: string;
  user: string;
  password: string | null;
  schemas: string[];
}

export interface TestResult { ok: boolean; tables: string[]; error: string | null }

export interface ColumnRef { schema: string | null; table: string; column: string }
export interface Candidate extends ColumnRef { score: number }

export type EntryStatus = "suggested" | "accepted" | "overridden" | "not_available" | "unmapped";

export interface Entry {
  field_id: string;
  label: string;
  section: string;
  required: boolean;
  source: ColumnRef | null;
  score: number;
  decided_by: "A" | "B" | "C" | "key" | "user" | "none";
  reason: string;
  warnings: string[];
  candidates: Candidate[];
  status: EntryStatus;
}

export interface Join { schema: string | null; table: string; kind: "one_to_one" | "many_to_one"; on: [string, string][] }
/** An excluded table; `join` is present when the user disabled a join, so it can be re-enabled. */
export interface Excluded { table: string; reason: string; join?: Join }
export interface JoinPlan { grain: ColumnRef; joins: Join[]; excluded: Excluded[] }

export interface Run {
  id: number;
  connection_id: number;
  status: "running" | "ready" | "failed" | "published";
  layers: string;
  warnings: string[];
  error: string | null;
  llm_calls: number;
  llm_tokens: number;
  join_plan_confirmed: boolean;
  created_at: string;
  finished_at: string | null;
}

export interface RunDetail {
  run: Run;
  join_plan: JoinPlan | null;
  entries: Entry[];
  blockers: string[];
  affected_calculated: string[];
}

export interface CatalogSection { id: string; label: string }
export interface Catalog { sections: CatalogSection[]; fields: CatalogField[] }
export interface ColumnInfo extends ColumnRef { type: string }
export interface Preview { columns: string[]; rows: unknown[][] }
export interface Published { ddl: string; row_count: number; schema: string }

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.detail as { blockers?: string[]; error?: string; errors?: { block_id: string | null; messages: string[] }[] }
      | string | (string | { msg?: string })[];
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : x.msg ?? JSON.stringify(x))).join("; ");
    if (d?.blockers) return `Cannot publish: ${d.blockers.join("; ")}`;
    if (d?.errors) return d.errors.map((e) => e.messages.join("; ")).join(" · ");
    if (d?.error) return d.error;
  }
  return String(err);
}

export interface Val { raw: number | string | boolean | null; display: string }
export interface Delta { raw: number; display: string; direction: "up" | "down" | "flat"; good: boolean | null }
export interface Kpi {
  key: string; label: string; unit: string; value: Val; previous: Val; delta: Delta | null;
  sparkline?: { month: string; raw: number | null }[];
}
export interface ColumnMeta { key: string; label: string; kind: "dimension" | "measure"; unit?: string }
export type BlockType = "heading" | "text" | "kpi_row" | "kpi" | "table" | "chart" | "page_break";
export type ChartType = "bar" | "stacked_bar" | "line" | "area" | "pie";
export interface BlockResult {
  id: string; type: BlockType; error?: string; text?: string; level?: number; title?: string | null;
  items?: Kpi[]; kpi?: Kpi; columns?: ColumnMeta[]; rows?: Record<string, Val>[];
  totals?: Record<string, Val> | null; empty?: boolean; chart?: ChartType;
}
export interface Rendered {
  client: { id: number; name: string };
  period: { start: string; end: string; prev_start: string; prev_end: string; label: string };
  generated_at: string;
  blocks: BlockResult[];
}
export type Agg = "count" | "count_distinct" | "sum" | "avg" | "min" | "max";
export interface Measure { metric?: string; field?: string; agg?: Agg; label?: string | null }
export type Filter = [string, string, unknown?];
export interface QuerySpec {
  measures: Measure[]; group_by: string[]; filters: Filter[];
  sort?: { by: string; dir: "asc" | "desc" } | null; limit?: number | null;
}
export interface Block {
  id: string; type: BlockType; text?: string; level?: number; title?: string | null;
  items?: { measure: Measure; label?: string | null }[]; measure?: Measure; label?: string | null;
  filters?: Filter[]; sparkline?: boolean; query?: QuerySpec; totals?: boolean; chart?: ChartType;
}
export interface Tile { id: string; block: Block; width: 3 | 4 | 6 | 8 | 12; height: "s" | "m" | "l" }
export interface PeriodSpec { preset: string; start?: string; end?: string }
export interface ReportSummary { id: number; name: string; description: string; updated_at: string }
export interface ReportTemplate extends ReportSummary { blocks: Block[] }
export interface DashboardSummary { id: number; name: string; default_period: PeriodSpec; updated_at: string }
export interface Dashboard extends DashboardSummary { tiles: Tile[] }
export interface Metric { id: string; label: string; unit: string; better: string; group: string; description: string }
export interface PublishedConnection { id: number; name: string; dialect: string; published_at: string }
export interface CatalogField {
  id: string; label: string; section: string; kind: string; type: string; role: string;
  values: string[] | null; unit: string | null;
}
