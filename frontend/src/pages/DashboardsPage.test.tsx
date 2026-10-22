// frontend/src/pages/DashboardsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Dashboard } from "../api";
import { DashboardsPage } from "./DashboardsPage";
import { mockApi, renderWithProviders } from "../test/render";
import { meAdmin, meClient } from "../test/fixtures";
import { echoRender, FIELDS, METRICS } from "../test/reporting";

const board: Dashboard = {
  id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "",
  shared: false, editable: true, owner: { id: 1, name: "NovaBank" },
  tiles: [
    { id: "t1", width: 3, height: "m", block: { id: "b1", type: "kpi", measure: { metric: "applications" }, filters: [] } },
    { id: "t2", width: 6, height: "l", block: { id: "b2", type: "chart", chart: "bar",
      query: { measures: [{ metric: "applications" }], group_by: ["channel"], filters: [] } } },
  ],
};

describe("DashboardsPage", () => {
  it("renders tiles, then edits width and order and saves them", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meClient,
      "GET /api/dashboards": [{ id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "",
                                shared: false, editable: true, owner: { id: 1, name: "NovaBank" } }],
      "GET /api/dashboards/1": board,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/render-blocks": echoRender,
      "PUT /api/dashboards/1": (_u: string, init?: RequestInit) => ({ ...board, ...JSON.parse(String(init!.body)) }),
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    expect(await screen.findByText("rendered b1")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/dashboards/1/render")?.body).toEqual({ period: { preset: "last_month" } });

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
  it("offers only Save as copy on a shared dashboard", async () => {
    const sharedBoard = { ...board, shared: true, editable: false, owner: null };
    const calls = mockApi({
      "GET /api/auth/me": meClient,
      "GET /api/dashboards": [{ ...sharedBoard, tiles: undefined }],
      "GET /api/dashboards/1": sharedBoard,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/dashboards": (_u: string, init?: RequestInit) => ({ ...sharedBoard, id: 9, shared: false, editable: true, ...JSON.parse(String(init!.body)) }),
      "GET /api/dashboards/9": { ...board, id: 9 },
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    expect(await screen.findByText("Shared")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save as copy" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/dashboards")?.body)
      .toMatchObject({ name: "Lending KPIs (copy)" }));
  });

  it("lets the admin save a private copy for the selected client", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meAdmin,
      "GET /api/dashboards": [{ id: 1, name: "Lending KPIs", default_period: { preset: "last_month" }, updated_at: "", shared: true, editable: true, owner: null }],
      "GET /api/dashboards/1": { ...board, shared: true, editable: true, owner: null },
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "POST /api/dashboards/1/render": (u: string, init?: RequestInit) =>
        echoRender(u, { body: JSON.stringify({ blocks: board.tiles.map((t) => t.block) }), method: init?.method }),
      "POST /api/dashboards": (_u: string, init?: RequestInit) => ({ ...board, id: 9, ...JSON.parse(String(init!.body)) }),
      "GET /api/dashboards/9": { ...board, id: 9 },
    });
    renderWithProviders(<DashboardsPage />, { route: "/dashboards/1", path: "/dashboards/:id" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Save as…" }));
    await user.click(screen.getByRole("radio", { name: "Only NovaBank" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/dashboards")?.body)
      .toMatchObject({ shared: false }));
  });
});
