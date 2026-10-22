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
  decided_by: "A" | "B" | "C" | "key" | "none";
  reason: string;
  warnings: string[];
  candidates: Candidate[];
  status: EntryStatus;
}

export interface Join { schema: string | null; table: string; kind: "one_to_one" | "many_to_one"; on: [string, string][] }
export interface JoinPlan { grain: ColumnRef; joins: Join[]; excluded: { table: string; reason: string }[] }

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
export interface Catalog { sections: CatalogSection[] }
export interface ColumnInfo extends ColumnRef { type: string }
export interface Preview { columns: string[]; rows: unknown[][] }
export interface Published { ddl: string; row_count: number; schema: string }
