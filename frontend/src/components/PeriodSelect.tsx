// frontend/src/components/PeriodSelect.tsx
import { Group, Select } from "@mantine/core";
import { DatePickerInput, type DatesRangeValue } from "@mantine/dates";
import dayjs from "dayjs";
import type { PeriodSpec } from "../api";

const PRESETS = [
  { value: "this_month", label: "This month" }, { value: "last_month", label: "Last month" },
  { value: "this_quarter", label: "This quarter" }, { value: "last_quarter", label: "Last quarter" },
  { value: "ytd", label: "Year to date" }, { value: "last_12_months", label: "Last 12 months" },
  { value: "custom", label: "Custom range" },
];

export const periodReady = (p: PeriodSpec | null): boolean =>
  !!p && (p.preset !== "custom" || (!!p.start && !!p.end));

const toDate = (s?: string) => (s ? dayjs(s).toDate() : null);
const toIso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : undefined);

export function PeriodSelect({ value, onChange }: { value: PeriodSpec; onChange: (p: PeriodSpec) => void }) {
  return (
    <Group gap="xs" align="flex-end">
      <Select label="Period" w={170} data={PRESETS} value={value.preset} allowDeselect={false}
        onChange={(p) => onChange(p === "custom" ? { preset: "custom", start: value.start, end: value.end } : { preset: p! })} />
      {value.preset === "custom" && (
        <DatePickerInput type="range" label="Dates" w={260} placeholder="Pick dates"
          value={[toDate(value.start), toDate(value.end)]}
          onChange={([s, e]: DatesRangeValue) => onChange({ preset: "custom", start: toIso(s), end: toIso(e) })} />
      )}
    </Group>
  );
}
