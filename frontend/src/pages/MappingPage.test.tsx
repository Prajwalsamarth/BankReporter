import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MappingPage } from "./MappingPage";
import { catalog, connections, runDetail } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/render";

const ROUTE = { route: "/connections/7/mapping", path: "/connections/:id/mapping" };

function setup(detail = runDetail(), extra: Record<string, unknown> = {}) {
  const calls = mockApi({
    "GET /api/catalog": catalog,
    "GET /api/connections": connections,
    "GET /api/connections/7/mapping-runs/latest": detail,
    "GET /api/mapping-runs/3": detail,
    ...extra,
  });
  renderWithProviders(<MappingPage />, ROUTE);
  return calls;
}

describe("MappingPage", () => {
  it("shows header counts, join plan and fields grouped by section", async () => {
    setup();
    expect(await screen.findByText("NovaBank")).toBeInTheDocument();
    expect(screen.getByText("Mapped 3/4 · Required 3/3")).toBeInTheDocument();
    expect(screen.getByText(/Grain: los\.loan_application \(application_id\)/)).toBeInTheDocument();
    expect(screen.getByText(/LEFT JOIN los\.customer ON customer_id = customer_id \(many-to-one\)/)).toBeInTheDocument();
    expect(screen.getByText(/los\.audit_log: no join path/)).toBeInTheDocument();
    expect(screen.getByText("Bureau (CIBIL)")).toBeInTheDocument();
    expect(screen.getByText("bureau_report.monthly_emi_obligations")).toBeInTheDocument();
  });

  it("filters to unmapped fields", async () => {
    setup();
    await userEvent.setup().click(await screen.findByRole("radio", { name: "Unmapped" }));
    expect(screen.getByText("Card Utilisation %")).toBeInTheDocument();
    expect(screen.queryByText("CIBIL Score")).not.toBeInTheDocument();
  });

  it("needs-review filter shows low-score and unmapped fields only", async () => {
    setup();
    await userEvent.setup().click(await screen.findByRole("radio", { name: "Needs review" }));
    expect(screen.getByText("Existing Monthly EMIs")).toBeInTheDocument();
    expect(screen.getByText("Card Utilisation %")).toBeInTheDocument();
    expect(screen.queryByText("CIBIL Score")).not.toBeInTheDocument();
  });

  it("accept, not-available and reset send the matching PATCH", async () => {
    const calls = setup(undefined, {
      "PATCH /api/mapping-runs/3/entries/cibil_score": {},
      "PATCH /api/mapping-runs/3/entries/existing_emi_monthly": {},
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Accept CIBIL Score" }));
    await user.click(screen.getByRole("button", { name: "Not available Existing Monthly EMIs" }));
    await user.click(screen.getByRole("button", { name: "Reset Existing Monthly EMIs" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { action: "accept" }, { action: "not_available" }, { action: "reset" },
    ]));
  });

  it("choosing an alternative sends the column", async () => {
    const calls = setup(undefined, { "PATCH /api/mapping-runs/3/entries/existing_emi_monthly": {} });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Alternatives for Existing Monthly EMIs" }));
    await user.click(await screen.findByRole("menuitem", { name: /bureau_report\.total_outstanding/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual(
      { action: "choose", schema: "los", table: "bureau_report", column: "total_outstanding" }));
  });

  it("shows a conflict from the server", async () => {
    setup(undefined, {
      "PATCH /api/mapping-runs/3/entries/cibil_score": () => new Response(
        JSON.stringify({ detail: "los.customer.state is already the source of State" }), { status: 409 }),
    });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Accept CIBIL Score" }));
    expect(await screen.findByText("los.customer.state is already the source of State")).toBeInTheDocument();
  });

  it("disables Publish and lists blockers in its tooltip", async () => {
    setup();
    const publish = await screen.findByRole("button", { name: "Publish" });
    expect(publish).toBeDisabled();
    await userEvent.setup().hover(publish.parentElement!);
    expect(await screen.findByText("Join plan not confirmed")).toBeInTheDocument();
  });

  it("confirms the join plan and publishes when unblocked", async () => {
    const ready = runDetail({ blockers: [], run: { ...runDetail().run, join_plan_confirmed: true } });
    const calls = setup(ready, {
      "POST /api/mapping-runs/3/publish": { ddl: "CREATE VIEW ...", row_count: 2000, schema: "lending_rpt" },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Published 2000 rows to lending_rpt.applications")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/publish"))).toBe(true);
  });

  it("confirming the join plan sends it back", async () => {
    const calls = setup(undefined, { "PUT /api/mapping-runs/3/join-plan": runDetail() });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Confirm join plan" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(put?.body).toEqual({ join_plan: runDetail().join_plan, confirmed: true });
    });
  });

  it("toggling a join off removes it from the confirmed plan", async () => {
    const calls = setup(undefined, { "PUT /api/mapping-runs/3/join-plan": runDetail() });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit join plan" }));
    await user.click(screen.getByRole("checkbox", { name: "los.bureau_report" }));
    await user.click(screen.getByRole("button", { name: "Confirm join plan" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "PUT")?.body as { join_plan: { joins: { table: string }[] } };
      expect(body.join_plan.joins.map((j) => j.table)).toEqual(["customer"]);
    });
  });

  it("shows the LLM-off banner and run errors", async () => {
    setup(runDetail({ run: { ...runDetail().run, warnings: ["llm_disabled"] } }));
    expect(await screen.findByText(/LLM layer off/)).toBeInTheDocument();
  });

  it("offers to start the first run when there is none", async () => {
    const calls = setup(undefined, {
      "GET /api/connections/7/mapping-runs/latest": () => new Response(JSON.stringify({ detail: "none" }), { status: 404 }),
      "POST /api/connections/7/mapping-runs": { run_id: 3, status: "running" },
    });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Run mapping" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/mapping-runs"))).toBe(true));
  });

  it("lists calculated fields that will be null", async () => {
    setup(runDetail({ affected_calculated: ["foir_pct", "post_loan_foir_pct"] }));
    const panel = await screen.findByText("Calculated fields that will always be empty");
    expect(within(panel.parentElement!).getByText("foir_pct, post_loan_foir_pct")).toBeInTheDocument();
  });
});
