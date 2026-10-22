// frontend/src/pages/ReportsPage.test.tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReportsPage } from "./ReportsPage";
import { mockApi, renderWithProviders } from "../test/render";

const rendered = {
  client: { id: 7, name: "NovaBank" },
  period: { start: "2026-09-01", end: "2026-09-30", prev_start: "2026-08-01", prev_end: "2026-08-31", label: "Sep 2026" },
  generated_at: "2026-10-22T18:05:00",
  blocks: [{ id: "h1", type: "heading", text: "Personal Loans MIS — NovaBank", level: 1 },
           { id: "bad", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }],
};

describe("ReportsPage", () => {
  it("renders the first template for the first client and prints to PDF", async () => {
    const calls = mockApi({
      "GET /api/reports": [{ id: 1, name: "Monthly Lending MIS", description: "", updated_at: "" }],
      "GET /api/connections/published": [{ id: 7, name: "NovaBank", dialect: "postgresql", published_at: "" }],
      "POST /api/reports/1/render": rendered,
    });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<ReportsPage />, { route: "/reports", path: "/reports" });
    expect(await screen.findByText("Personal Loans MIS — NovaBank")).toBeInTheDocument();
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(screen.getByText(/Sep 2026/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ connection_id: 7, period: { preset: "last_month" } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Download PDF" }));
    expect(print).toHaveBeenCalled();
  });

  it("deletes a template only after an in-page confirmation", async () => {
    const calls = mockApi({
      "GET /api/reports": [{ id: 1, name: "Mine", description: "", updated_at: "" }],
      "GET /api/connections/published": [],
      "DELETE /api/reports/1": undefined,
    });
    renderWithProviders(<ReportsPage />, { route: "/reports", path: "/reports" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete template" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
