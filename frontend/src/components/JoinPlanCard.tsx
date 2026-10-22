import { Badge, Button, Card, Checkbox, Group, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { Excluded, Join, JoinPlan } from "../api";

const qualified = (schema: string | null, table: string) => (schema ? `${schema}.${table}` : table);
const keyOf = (j: Join) => qualified(j.schema, j.table);
const kindLabel = { one_to_one: "one-to-one", many_to_one: "many-to-one" } as const;
const DISABLED = "disabled by user";

interface Props {
  plan: JoinPlan;
  confirmed: boolean;
  saving: boolean;
  onConfirm: (plan: JoinPlan) => void;
}

/**
 * Joins can be switched off and back on; switched-off joins travel in `excluded` with their definition.
 * State is keyed by "schema.table" (not object identity), so refetched plans keep their selection.
 * The grain is read-only here: changing it needs primary-key information only the server has, so re-run instead.
 */
export function JoinPlanCard({ plan, confirmed, saving, onConfirm }: Props) {
  const candidates: Join[] = [...plan.joins, ...plan.excluded.flatMap((x) => (x.join ? [x.join] : []))];
  const [enabled, setEnabled] = useState<Set<string>>(() => new Set(plan.joins.map(keyOf)));
  const [editing, setEditing] = useState(false);
  const toggle = (k: string) => setEnabled((s) => {
    const next = new Set(s);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });

  function confirm() {
    setEditing(false);
    const joins = candidates.filter((j) => enabled.has(keyOf(j)));
    const excluded: Excluded[] = [
      ...plan.excluded.filter((x) => !x.join),
      ...candidates.filter((j) => !enabled.has(keyOf(j))).map((j) => ({ table: keyOf(j), reason: DISABLED, join: j })),
    ];
    onConfirm({ ...plan, joins, excluded });
  }

  const line = (j: Join) =>
    `LEFT JOIN ${keyOf(j)} ON ${j.on.map(([l, r]) => `${l} = ${r}`).join(" AND ")} (${kindLabel[j.kind]})`;

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>Join plan</Text>
          {confirmed ? <Badge color="teal">Confirmed</Badge> : <Badge color="orange">Not confirmed</Badge>}
        </Group>
        <Group gap="xs">
          <Button size="xs" variant="default" onClick={() => setEditing((e) => !e)}>
            {editing ? "Done editing" : "Edit join plan"}
          </Button>
          <Button size="xs" loading={saving} onClick={confirm}>Confirm join plan</Button>
        </Group>
      </Group>
      <Stack gap={4}>
        <Text size="sm" ff="monospace">
          Grain: {qualified(plan.grain.schema, plan.grain.table)} ({plan.grain.column})
        </Text>
        {editing
          ? candidates.map((j) => (
              <Checkbox key={keyOf(j)} label={keyOf(j)} description={line(j)}
                checked={enabled.has(keyOf(j))} onChange={() => toggle(keyOf(j))} />
            ))
          : candidates.filter((j) => enabled.has(keyOf(j))).map((j) => (
              <Text key={keyOf(j)} size="sm" ff="monospace">{line(j)}</Text>
            ))}
        {!editing && candidates.filter((j) => !enabled.has(keyOf(j))).map((j) => (
          <Text key={keyOf(j)} size="sm" c="dimmed">Excluded {keyOf(j)}: {DISABLED}</Text>
        ))}
        {plan.excluded.filter((x) => !x.join).map((x) => (
          <Text key={x.table} size="sm" c="dimmed">Excluded {x.table}: {x.reason}</Text>
        ))}
      </Stack>
    </Card>
  );
}
