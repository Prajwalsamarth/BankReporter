import { Badge, Button, Card, Checkbox, Group, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { Join, JoinPlan } from "../api";

const qualified = (schema: string | null, table: string) => (schema ? `${schema}.${table}` : table);
const kindLabel = { one_to_one: "one-to-one", many_to_one: "many-to-one" } as const;

interface Props {
  plan: JoinPlan;
  confirmed: boolean;
  saving: boolean;
  onConfirm: (plan: JoinPlan) => void;
}

/** The grain is read-only here: changing it needs primary-key information only the server has, so re-run instead. */
export function JoinPlanCard({ plan, confirmed, saving, onConfirm }: Props) {
  const [editing, setEditing] = useState(false);
  const [included, setIncluded] = useState<Set<Join>>(new Set(plan.joins));
  const joins = editing ? plan.joins : plan.joins.filter((j) => included.has(j));
  const toggle = (j: Join) => setIncluded((s) => {
    const next = new Set(s);
    if (next.has(j)) next.delete(j); else next.add(j);
    return next;
  });

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
          <Button size="xs" loading={saving}
            onClick={() => { setEditing(false); onConfirm({ ...plan, joins: plan.joins.filter((j) => included.has(j)) }); }}>
            Confirm join plan
          </Button>
        </Group>
      </Group>
      <Stack gap={4}>
        <Text size="sm" ff="monospace">
          Grain: {qualified(plan.grain.schema, plan.grain.table)} ({plan.grain.column})
        </Text>
        {joins.map((j) => {
          const line = `LEFT JOIN ${qualified(j.schema, j.table)} ON ${j.on.map(([l, r]) => `${l} = ${r}`).join(" AND ")} (${kindLabel[j.kind]})`;
          return editing ? (
            <Checkbox key={qualified(j.schema, j.table)} label={qualified(j.schema, j.table)}
              description={line} checked={included.has(j)} onChange={() => toggle(j)} />
          ) : (
            <Text key={qualified(j.schema, j.table)} size="sm" ff="monospace">{line}</Text>
          );
        })}
        {plan.excluded.map((x) => (
          <Text key={x.table} size="sm" c="dimmed">Excluded {x.table}: {x.reason}</Text>
        ))}
      </Stack>
    </Card>
  );
}
