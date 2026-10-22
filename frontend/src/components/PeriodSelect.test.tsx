// frontend/src/components/PeriodSelect.test.tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PeriodSpec } from "../api";
import { PeriodSelect, periodReady } from "./PeriodSelect";
import { renderWithProviders } from "../test/render";

function Harness({ onChange }: { onChange: (p: PeriodSpec) => void }) {
  const [value, setValue] = useState<PeriodSpec>({ preset: "last_month" });
  return <PeriodSelect value={value} onChange={(p) => { setValue(p); onChange(p); }} />;
}

describe("PeriodSelect", () => {
  it("switches to a custom range and shows date pickers", async () => {
    const onChange = vi.fn();
    renderWithProviders(<Harness onChange={onChange} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox", { name: "Period" }));
    await user.click(await screen.findByRole("option", { name: "Custom range" }));
    expect(onChange).toHaveBeenLastCalledWith({ preset: "custom", start: undefined, end: undefined });
    expect(screen.getByText("Dates")).toBeInTheDocument();
  });

  it("knows when a period is complete", () => {
    expect(periodReady({ preset: "ytd" })).toBe(true);
    expect(periodReady({ preset: "custom", start: "2026-01-01" })).toBe(false);
    expect(periodReady({ preset: "custom", start: "2026-01-01", end: "2026-01-31" })).toBe(true);
  });
});
