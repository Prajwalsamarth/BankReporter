import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ConnectionsPage } from "./ConnectionsPage";
import { mockApi, renderWithProviders } from "../test/render";

const conn = {
  id: 7, name: "NovaBank", dialect: "postgresql", schemas: ["los"], needs_password: false,
  url_masked: "postgresql+psycopg://novabank:***@localhost:5433/novabank",
};

describe("ConnectionsPage", () => {
  it("lists connections with masked URLs and a mapping link", async () => {
    mockApi({ "GET /api/connections": [conn] });
    renderWithProviders(<ConnectionsPage />);
    expect(await screen.findByText("NovaBank")).toBeInTheDocument();
    expect(screen.getByText(conn.url_masked)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open mapping" })).toHaveAttribute("href", "/connections/7/mapping");
  });

  it("shows the result of testing a connection", async () => {
    mockApi({
      "GET /api/connections": [conn],
      "POST /api/connections/7/test": { ok: true, tables: ["los.customer", "los.loan_application"], error: null },
    });
    renderWithProviders(<ConnectionsPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Test" }));
    expect(await screen.findByText("Connected · 2 tables")).toBeInTheDocument();
  });

  it("shows a failed test's error", async () => {
    mockApi({
      "GET /api/connections": [conn],
      "POST /api/connections/7/test": { ok: false, tables: [], error: "connection refused" },
    });
    renderWithProviders(<ConnectionsPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Test" }));
    expect(await screen.findByText("connection refused")).toBeInTheDocument();
  });

  it("asks for confirmation inside the page before deleting", async () => {
    const calls = mockApi({ "GET /api/connections": [conn], "DELETE /api/connections/7": undefined });
    renderWithProviders(<ConnectionsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("flags connections whose password must be re-entered", async () => {
    mockApi({ "GET /api/connections": [{ ...conn, url_masked: null, needs_password: true }] });
    renderWithProviders(<ConnectionsPage />);
    expect(await screen.findByText("Password needs re-entering")).toBeInTheDocument();
  });
});
