// frontend/src/components/BlockSettings.test.tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Block } from "../api";
import { BlockSettings } from "./BlockSettings";
import { renderWithProviders } from "../test/render";
import { FIELDS, METRICS } from "../test/reporting";

function Harness({ initial, onChange }: { initial: Block; onChange: (b: Block) => void }) {
  const [block, setBlock] = useState(initial);
  return <BlockSettings block={block} fields={FIELDS} metrics={METRICS}
    onChange={(b) => { setBlock(b); onChange(b); }} />;
}

const chart: Block = { id: "c", type: "chart", chart: "line", title: "T",
  query: { measures: [{ metric: "applications" }], group_by: ["application_month"], filters: [] } };

describe("BlockSettings", () => {
  it("changes the chart type and adds a typed filter", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness initial={chart} onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox", { name: "Chart type" }));
    await user.click(await screen.findByRole("option", { name: "Bar" }));
    expect(onChange.mock.lastCall![0].chart).toBe("bar");
    await user.click(screen.getByRole("button", { name: "Add filter" }));
    expect(onChange.mock.lastCall![0].query.filters).toEqual([["channel", "eq", "BRANCH"]]);
    await user.click(screen.getByRole("textbox", { name: "Filter 1 operator" }));
    await user.click(await screen.findByRole("option", { name: "is one of" }));
    expect(onChange.mock.lastCall![0].query.filters).toEqual([["channel", "in", ["BRANCH"]]]);
  });

  it("switches a measure to a field aggregate", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness initial={chart} onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox", { name: "Measure 1" }));
    await user.click(await screen.findByRole("option", { name: "Field aggregate…" }));
    expect(onChange.mock.lastCall![0].query.measures).toEqual([{ field: "disbursed_amount", agg: "sum" }]);
  });

  it("adds and removes KPI items, capped at 6", async () => {
    const onChange = vi.fn();
    const row: Block = { id: "k", type: "kpi_row", filters: [], items: [{ measure: { metric: "applications" } }] };
    renderWithProviders(<Harness initial={row} onChange={onChange} />);
    const user = userEvent.setup();
    for (let i = 0; i < 6; i++) await user.click(screen.getByRole("button", { name: "Add KPI" }));
    expect(onChange.mock.lastCall![0].items).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Add KPI" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Remove KPI 1" }));
    expect(onChange.mock.lastCall![0].items).toHaveLength(5);
  });
});

describe("BlockSettings regressions", () => {
  it("adds a measure without duplicating one already used (final review #1)", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness initial={chart} onChange={onChange} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Add measure" }));
    expect(onChange.mock.lastCall![0].query.measures).toEqual([{ metric: "applications" }, { metric: "approval_rate" }]);
    expect(screen.getByRole("textbox", { name: "Sort by" })).toBeInTheDocument();
  });

  it("does not crash when the same metric is chosen twice", async () => {
    const dup: Block = { ...chart, query: { ...chart.query!, measures: [{ metric: "applications" }, { metric: "applications" }] } };
    renderWithProviders(<Harness initial={dup} onChange={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Sort by" })).toBeInTheDocument();
  });
});
