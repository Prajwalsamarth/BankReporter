// frontend/src/pages/DashboardsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Dashboard } from "../api";
import { DashboardsPage } from "./DashboardsPage";
import { mockApi, renderWithProviders } from "../test/render";
import { echoRender, FIELDS, METRICS } from "../test/reporting";

const board: Dashboard = {
  id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "",
  tiles: [
    { id: "t1", width: 3, height: "m", block: { id: "b1", type: "kpi", measure: { metric: "applications" }, filters: [] } },
    { id: "t2", width: 6, height: "l", block: { id: "b2", type: "chart", chart: "bar",
      query: { measures: [{ metric: "applications" }], group_by: ["channel"], filters: [] } } },
  ],
};

describe("DashboardsPage", () => {
  it("renders tiles, then edits width and order and saves them", async () => {
    const calls = mockApi({
      "GET /api/dashboards": [{ id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "" }],
      "GET /api/dashboards/1": board,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "GET /api/connections/published": [{ id: 7, name: "NovaBank", dialect: "postgresql", published_at: "" }],
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/render-blocks": echoRender,
      "PUT /api/dashboards/1": (_u: string, init?: RequestInit) => ({ ...board, ...JSON.parse(String(init!.body)) }),
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    expect(await screen.findByText("rendered b1")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/dashboards/1/render")?.body).toEqual({ connection_id: 7, period: { preset: "last_month" } });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("textbox", { name: "Width of tile 1" }));
    await user.click(await screen.findByRole("option", { name: "6" }));
    await user.click(screen.getByRole("button", { name: "Move tile 2 earlier" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "PUT")?.body as Dashboard;
      expect(body.tiles.map((t) => t.id)).toEqual(["t2", "t1"]);
      expect(body.tiles[1].width).toBe(6);
    });
  });
});
