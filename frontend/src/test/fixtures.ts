import type { Entry, RunDetail } from "../api";

export const entry = (over: Partial<Entry>): Entry => ({
  field_id: "x", label: "X", section: "application", required: false,
  source: { schema: "los", table: "t", column: "x" }, score: 1, decided_by: "A", reason: "name matches field id",
  warnings: [], candidates: [], status: "suggested", ...over,
});

export const runDetail = (over: Partial<RunDetail> = {}): RunDetail => ({
  run: {
    id: 3, connection_id: 7, status: "ready", layers: "ABC", warnings: [], error: null, llm_calls: 2,
    llm_tokens: 900, join_plan_confirmed: false, created_at: "2026-10-22T10:00:00", finished_at: "2026-10-22T10:00:09",
  },
  join_plan: {
    grain: { schema: "los", table: "loan_application", column: "application_id" },
    joins: [
      { schema: "los", table: "customer", kind: "many_to_one", on: [["customer_id", "customer_id"]] },
      { schema: "los", table: "bureau_report", kind: "one_to_one", on: [["application_id", "application_id"]] },
    ],
    excluded: [{ table: "los.audit_log", reason: "no join path to the grain table" }],
  },
  entries: [
    entry({ field_id: "application_id", label: "Application ID", required: true, decided_by: "key",
            source: { schema: "los", table: "loan_application", column: "application_id" }, reason: "grain table primary key" }),
    entry({ field_id: "cibil_score", label: "CIBIL Score", section: "bureau", required: true,
            source: { schema: "los", table: "bureau_report", column: "cibil_score" } }),
    entry({ field_id: "existing_emi_monthly", label: "Existing Monthly EMIs", section: "bureau", required: true,
            source: { schema: "los", table: "bureau_report", column: "monthly_emi_obligations" }, score: 0.72,
            decided_by: "C", reason: "monthly EMI obligations from bureau",
            candidates: [{ schema: "los", table: "bureau_report", column: "total_outstanding", score: 0.6 }] }),
    entry({ field_id: "card_utilization_pct", label: "Card Utilisation %", section: "bureau", source: null,
            score: 0, decided_by: "none", reason: "", status: "unmapped" }),
  ],
  blockers: ["Join plan not confirmed"],
  affected_calculated: [],
  ...over,
});

export const catalog = {
  sections: [{ id: "application", label: "Application" }, { id: "bureau", label: "Bureau (CIBIL)" }],
};
export const connections = [{ id: 7, name: "NovaBank", dialect: "postgresql", url_masked: "x", schemas: ["los"], needs_password: false }];
