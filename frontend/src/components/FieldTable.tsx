import { Accordion, ActionIcon, Badge, Group, Menu, Progress, SegmentedControl, Stack, Table, Text, Tooltip } from "@mantine/core";
import { useState } from "react";
import type { CatalogSection, ColumnRef, Entry } from "../api";

export type Filter = "all" | "review" | "unmapped" | "required";

export const needsReview = (e: Entry) =>
  (e.score < 0.9 && e.status !== "accepted" && e.status !== "overridden") || e.warnings.length > 0;

const matches: Record<Filter, (e: Entry) => boolean> = {
  all: () => true,
  review: needsReview,
  unmapped: (e) => e.source === null,
  required: (e) => e.required,
};

const byColor = { A: "blue", B: "grape", C: "orange", key: "gray", user: "teal", none: "gray" } as const;

export interface FieldActions {
  accept: (e: Entry) => void;
  choose: (e: Entry, ref: ColumnRef) => void;
  notAvailable: (e: Entry) => void;
  reset: (e: Entry) => void;
  searchAll: (e: Entry) => void;
}

function SourceCell({ e }: { e: Entry }) {
  if (e.status === "not_available") return <Text size="sm" c="dimmed">not available</Text>;
  if (!e.source) return <Text size="sm" c="dimmed">— unmapped —</Text>;
  return <Text size="sm" ff="monospace">{e.source.table}.{e.source.column}</Text>;
}

function FieldRow({ e, actions }: { e: Entry; actions: FieldActions }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Group gap={4} wrap="nowrap">
          <Text size="sm" fw={500}>{e.label}</Text>
          {e.required && <Text size="sm" c="red" aria-label="required">*</Text>}
        </Group>
        <Text size="xs" c="dimmed" ff="monospace">{e.field_id}</Text>
      </Table.Td>
      <Table.Td><SourceCell e={e} /></Table.Td>
      <Table.Td w={120}>
        {e.source && (
          <Group gap={6} wrap="nowrap">
            <Progress value={e.score * 100} w={50} color={e.score >= 0.9 ? "teal" : "orange"} />
            <Text size="xs">{e.score.toFixed(2)}</Text>
          </Group>
        )}
      </Table.Td>
      <Table.Td><Badge size="sm" variant="light" color={byColor[e.decided_by]}>{e.decided_by}</Badge></Table.Td>
      <Table.Td maw={260}>
        <Tooltip label={e.reason} disabled={!e.reason} multiline w={300}>
          <Text size="xs" truncate>{e.reason}</Text>
        </Tooltip>
      </Table.Td>
      <Table.Td>
        {e.warnings.length > 0 && (
          <Tooltip label={e.warnings.join("; ")} multiline w={300}>
            <Text size="sm" c="orange" aria-label={`Warnings for ${e.label}`}>⚠ {e.warnings.length}</Text>
          </Tooltip>
        )}
      </Table.Td>
      <Table.Td>
        <Group gap={4} wrap="nowrap">
          <ActionIcon variant="subtle" color="teal" aria-label={`Accept ${e.label}`}
            disabled={!e.source || e.status === "accepted"} onClick={() => actions.accept(e)}>✓</ActionIcon>
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon variant="subtle" aria-label={`Alternatives for ${e.label}`}>▾</ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {e.candidates.map((c) => (
                <Menu.Item key={`${c.schema}.${c.table}.${c.column}`} onClick={() => actions.choose(e, c)}>
                  {c.table}.{c.column} ({c.score.toFixed(2)})
                </Menu.Item>
              ))}
              {e.candidates.length > 0 && <Menu.Divider />}
              <Menu.Item onClick={() => actions.searchAll(e)}>Search all columns…</Menu.Item>
            </Menu.Dropdown>
          </Menu>
          <ActionIcon variant="subtle" color="gray" aria-label={`Not available ${e.label}`}
            disabled={e.status === "not_available"} onClick={() => actions.notAvailable(e)}>⊘</ActionIcon>
          <ActionIcon variant="subtle" color="gray" aria-label={`Reset ${e.label}`} onClick={() => actions.reset(e)}>↺</ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

export function FieldTable({ entries, sections, actions }: {
  entries: Entry[]; sections: CatalogSection[]; actions: FieldActions;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const visible = entries.filter(matches[filter]);
  const groups = sections.map((s) => ({ ...s, rows: visible.filter((e) => e.section === s.id) }))
    .filter((g) => g.rows.length > 0);

  return (
    <Stack>
      <SegmentedControl value={filter} onChange={(v) => setFilter(v as Filter)} w="fit-content"
        data={[{ value: "all", label: "All" }, { value: "review", label: "Needs review" },
               { value: "unmapped", label: "Unmapped" }, { value: "required", label: "Required" }]} />
      {groups.length === 0 && <Text c="dimmed">No fields match this filter.</Text>}
      <Accordion multiple defaultValue={sections.map((s) => s.id)} variant="separated">
        {groups.map((g) => (
          <Accordion.Item key={g.id} value={g.id}>
            <Accordion.Control>{g.label}</Accordion.Control>
            <Accordion.Panel>
              <Table>
                <Table.Thead><Table.Tr>
                  <Table.Th>Field</Table.Th><Table.Th>Source</Table.Th><Table.Th>Confidence</Table.Th>
                  <Table.Th>By</Table.Th><Table.Th>Reason</Table.Th><Table.Th /><Table.Th>Actions</Table.Th>
                </Table.Tr></Table.Thead>
                <Table.Tbody>{g.rows.map((e) => <FieldRow key={e.field_id} e={e} actions={actions} />)}</Table.Tbody>
              </Table>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}
