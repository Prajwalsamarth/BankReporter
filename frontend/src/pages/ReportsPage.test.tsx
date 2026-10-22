// frontend/src/pages/ReportsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";
import { meAdmin, meClient } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/render";

const rendered = {
  client: { id: 7, name: "NovaBank" },
  period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
  generated_at: "2026-10-22T18:05:00",
  blocks: [{ id: "h1", type: "heading", text: "Personal Loans MIS — NovaBank", level: 1 },
           { id: "bad", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }],
};
const shared = { id: 1, name: "Monthly Lending MIS", description: "", updated_at: "", shared: true, editable: false, owner: null };
const mine = { id: 2, name: "Mine", description: "", updated_at: "", shared: false, editable: true, owner: { id: 1, name: "NovaBank" } };
const ROUTE = { route: "/reports", path: "/reports" };

describe("ReportsPage", () => {
  it("renders the first template for the signed-in client and prints to PDF", async () => {
    const calls = mockApi({ "GET /api/auth/me": meClient, "GET /api/reports": [shared], "POST /api/reports/1/render": rendered });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Personal Loans MIS — NovaBank")).toBeInTheDocument();
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ period: { preset: "last_month" } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Download PDF" }));
    expect(print).toHaveBeenCalled();
  });

  it("offers only Save as for a shared template", async () => {
    mockApi({ "GET /api/auth/me": meClient, "GET /api/reports": [shared], "POST /api/reports/1/render": rendered });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Shared")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Save as…" })).toHaveAttribute("href", "/reports/1/edit");
    expect(screen.queryByRole("link", { name: "Edit template" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete template" })).not.toBeInTheDocument();
  });

  it("deletes an own template only after an in-page confirmation", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meClient, "GET /api/reports": [mine],
      "POST /api/reports/2/render": rendered, "DELETE /api/reports/2": undefined,
    });
    renderWithProviders(<ReportsPage />, ROUTE);
    const user = userEvent.setup();
    expect(await screen.findByText("Private")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Delete template" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("asks the admin to choose a client before rendering", async () => {
    const calls = mockApi({ "GET /api/auth/me": { ...meAdmin, client: null }, "GET /api/reports": [shared] });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Choose a client in the header to see data")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("explains an unpublished mapping and links to it", async () => {
    mockApi({
      "GET /api/auth/me": meClient, "GET /api/reports": [shared],
      "POST /api/reports/1/render": () => new Response(JSON.stringify(
        { detail: "NovaBank has no published views; publish its mapping first" }), { status: 409 }),
      "GET /api/connections": [{ id: 7, name: "NovaBank", dialect: "postgresql", url_masked: "x", schemas: ["los"],
                                 needs_password: false, client: { id: 1, name: "NovaBank" } }],
    });
    renderWithProviders(<ReportsPage />, ROUTE);
    expect(await screen.findByText("Your data mapping isn't published yet")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open the mapping" })).toHaveAttribute("href", "/connections/7/mapping");
  });
});
