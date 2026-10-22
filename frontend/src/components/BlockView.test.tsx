// frontend/src/components/BlockView.test.tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BlockView } from "./BlockView";
import { renderWithProviders } from "../test/render";
import { kpi } from "../test/reporting";

const goodOf = (text: RegExp) => screen.getByText(text).closest("[data-good]")?.getAttribute("data-good");

describe("BlockView", () => {
  it("colours KPI deltas by whether the change is good", () => {
    renderWithProviders(<>
      <BlockView result={{ id: "a", type: "kpi", kpi: kpi() }} />
      <BlockView result={{ id: "b", type: "kpi", kpi: kpi({ key: "tat", label: "TAT",
        delta: { raw: 5, display: "+5.0%", direction: "up", good: false } }) }} />
      <BlockView result={{ id: "c", type: "kpi", kpi: kpi({ key: "x", label: "Ticket",
        delta: { raw: 1, display: "+1.0%", direction: "up", good: null } }) }} />
    </>);
    expect(goodOf(/\+2\.1 pts/)).toBe("true");
    expect(goodOf(/\+5\.0%/)).toBe("false");
    expect(goodOf(/\+1\.0%/)).toBe("null");
    expect(screen.getAllByText("61.2%")).toHaveLength(3);
    expect(screen.getAllByText(/prev 59\.1%/)).toHaveLength(3);
  });

  it("shows a failed block's error while its sibling still renders", () => {
    renderWithProviders(<>
      <BlockView result={{ id: "a", type: "chart", error: "invalid block: measure 1: unknown metric 'gone'" }} />
      <BlockView result={{ id: "b", type: "heading", text: "Turnaround", level: 2 }} />
    </>);
    expect(screen.getByText("invalid block: measure 1: unknown metric 'gone'")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Turnaround" })).toBeInTheDocument();
  });

  it("renders tables with totals, and empty results", () => {
    const columns = [{ key: "channel", label: "Channel", kind: "dimension" as const },
                     { key: "applications", label: "Applications", kind: "measure" as const, unit: "count" }];
    renderWithProviders(<>
      <BlockView result={{ id: "t", type: "table", title: "By channel", columns, empty: false,
        rows: [{ channel: { raw: "WEB", display: "WEB" }, applications: { raw: 12, display: "12" } }],
        totals: { applications: { raw: 12, display: "12" } } }} />
      <BlockView result={{ id: "e", type: "chart", chart: "bar", columns, rows: [], empty: true }} />
    </>);
    expect(screen.getByText("By channel")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("No applications in this period")).toBeInTheDocument();
  });
});
