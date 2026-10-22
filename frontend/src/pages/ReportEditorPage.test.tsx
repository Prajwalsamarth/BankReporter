// frontend/src/pages/ReportEditorPage.test.tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReportEditorPage } from "./ReportEditorPage";
import { mockApi, renderWithProviders } from "../test/render";
import { meClient } from "../test/fixtures";
import { echoRender, FIELDS, METRICS } from "../test/reporting";

function setup() {
  const calls = mockApi({
    "GET /api/catalog": { sections: [], fields: FIELDS },
    "GET /api/metrics": METRICS,
    "GET /api/auth/me": meClient,
    "POST /api/render-blocks": echoRender,
    "POST /api/reports": (_u: string, init?: RequestInit) => ({ id: 5, updated_at: "", ...JSON.parse(String(init!.body)) }),
  });
  renderWithProviders(<ReportEditorPage />, { route: "/reports/new", path: "/reports/new" });
  return calls;
}

const listItems = () => within(screen.getByTestId("block-list")).getAllByTestId("block-item").map((el) => el.textContent);

describe("ReportEditorPage", () => {
  it("adds, moves, duplicates and deletes blocks, previews them, and saves", async () => {
    const calls = setup();
    const user = userEvent.setup();
    const add = async (label: string) => {
      await user.click(await screen.findByRole("button", { name: "Add block" }));
      await user.click(await screen.findByRole("menuitem", { name: label }));
    };
    await add("Heading");
    await add("Page break");
    expect(listItems()).toEqual([expect.stringContaining("Heading: New section"), expect.stringContaining("Page break")]);

    await user.click(screen.getByRole("button", { name: "Move block 2 up" }));
    expect(listItems()[0]).toContain("Page break");
    await user.click(screen.getByRole("button", { name: "Duplicate block 2" }));
    expect(listItems()).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Delete block 1" }));
    expect(listItems()).toEqual([expect.stringContaining("Heading"), expect.stringContaining("Heading")]);

    expect((await screen.findAllByText(/^rendered /, {}, { timeout: 2000 })).length).toBeGreaterThan(0);
    expect(calls.some((c) => c.path === "/api/render-blocks")).toBe(true);

    await user.clear(screen.getByLabelText("Template name"));
    await user.type(screen.getByLabelText("Template name"), "Weekly pack");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "POST" && c.path === "/api/reports")?.body as { name: string; blocks: { type: string }[] };
      expect(body.name).toBe("Weekly pack");
      expect(body.blocks.map((b) => b.type)).toEqual(["heading", "heading"]);
    });
  });

  it("asks before discarding unsaved changes", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add block" }));
    await user.click(await screen.findByRole("menuitem", { name: "Text" }));
    await user.click(screen.getByRole("button", { name: "Back to reports" }));
    expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
  });
});

describe("ReportEditorPage after saving (final review #2)", () => {
  it("shows the saved version when the template is reopened", async () => {
    const { MantineProvider } = await import("@mantine/core");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const { render } = await import("@testing-library/react");
    const { Link, MemoryRouter, Route, Routes } = await import("react-router-dom");
    let server = { id: 1, name: "v1", description: "", updated_at: "", blocks: [] as unknown[], shared: false, editable: true, owner: null };
    mockApi({
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "GET /api/auth/me": meClient,
      "GET /api/reports/1": () => server,
      "PUT /api/reports/1": (_u: string, init?: RequestInit) => (server = { ...server, ...JSON.parse(String(init!.body)) }),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MantineProvider><QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/reports/1/edit"]}>
          <Routes>
            <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
            <Route path="/reports" element={<Link to="/reports/1/edit">open again</Link>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider></MantineProvider>,
    );
    const user = userEvent.setup();
    const name = await screen.findByLabelText("Template name");
    await user.clear(name);
    await user.type(name, "v2");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    await user.click(screen.getByRole("button", { name: "Back to reports" }));
    await user.click(await screen.findByRole("link", { name: "open again" }));
    expect(await screen.findByLabelText("Template name")).toHaveValue("v2");
  });
});

describe("ReportEditorPage on a shared template", () => {
  it("saves a shared template only as a copy", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meClient,
      "GET /api/catalog": { sections: [], fields: FIELDS },
      "GET /api/metrics": METRICS,
      "GET /api/reports/1": { id: 1, name: "Monthly Lending MIS", description: "", updated_at: "", blocks: [],
                              shared: true, editable: false, owner: null },
      "POST /api/reports": (_u: string, init?: RequestInit) => ({ id: 5, updated_at: "", ...JSON.parse(String(init!.body)) }),
    });
    renderWithProviders(<ReportEditorPage />, { route: "/reports/1/edit", path: "/reports/:id/edit" });
    expect(await screen.findByLabelText("Template name")).toHaveValue("Monthly Lending MIS (copy)");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Save as copy" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/reports")).toBe(true));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
