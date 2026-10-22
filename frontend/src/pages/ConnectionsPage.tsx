import { Alert, Anchor, Badge, Button, Group, Modal, Stack, Table, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Connection, type ConnectionInput, type TestResult } from "../api";
import { ConnectionForm } from "../components/ConnectionForm";

function TestOutcome({ result }: { result: TestResult }) {
  return result.ok
    ? <Text size="sm" c="teal">Connected · {result.tables.length} tables</Text>
    : <Text size="sm" c="red">{result.error}</Text>;
}

function ConnectionRow({ conn, onEdit }: { conn: Connection; onEdit: () => void }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const test = useMutation({ mutationFn: () => api<TestResult>(`/connections/${conn.id}/test`, { method: "POST" }) });
  const remove = useMutation({
    mutationFn: () => api<void>(`/connections/${conn.id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
  });
  return (
    <Table.Tr>
      <Table.Td><Text fw={500}>{conn.name}</Text></Table.Td>
      <Table.Td><Badge variant="light">{conn.dialect}</Badge></Table.Td>
      <Table.Td>
        {conn.needs_password
          ? <Text size="sm" c="orange">Password needs re-entering</Text>
          : <Text size="sm" ff="monospace">{conn.url_masked}</Text>}
        {test.data && <TestOutcome result={test.data} />}
      </Table.Td>
      <Table.Td>{conn.schemas.join(", ")}</Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <Button size="xs" variant="default" onClick={() => test.mutate()} loading={test.isPending}>Test</Button>
          <Button size="xs" variant="default" onClick={onEdit}>Edit</Button>
          {confirming ? (
            <>
              <Button size="xs" color="red" onClick={() => remove.mutate()} loading={remove.isPending}>Confirm delete</Button>
              <Button size="xs" variant="subtle" onClick={() => setConfirming(false)}>Cancel</Button>
            </>
          ) : (
            <Button size="xs" variant="default" color="red" onClick={() => setConfirming(true)}>Delete</Button>
          )}
          <Anchor component={Link} to={`/connections/${conn.id}/mapping`} size="sm">Open mapping</Anchor>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

export function ConnectionsPage() {
  const qc = useQueryClient();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections") });
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const save = useMutation({
    mutationFn: (values: ConnectionInput) => editing === "new" || editing === null
      ? api<Connection>("/connections", { method: "POST", json: values })
      : api<Connection>(`/connections/${editing.id}`, { method: "PUT", json: values }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); setEditing(null); },
  });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Connections</Title>
        <Button onClick={() => { save.reset(); setEditing("new"); }}>Add connection</Button>
      </Group>
      {connections.isError && <Alert color="red">{String(connections.error)}</Alert>}
      {connections.data?.length === 0 && <Text c="dimmed">No connections yet. Add a client database to start mapping.</Text>}
      {!!connections.data?.length && (
        <Table verticalSpacing="sm">
          <Table.Thead><Table.Tr>
            <Table.Th>Name</Table.Th><Table.Th>Type</Table.Th><Table.Th>URL</Table.Th>
            <Table.Th>Schemas</Table.Th><Table.Th />
          </Table.Tr></Table.Thead>
          <Table.Tbody>
            {connections.data.map((c) => (
              <ConnectionRow key={c.id} conn={c} onEdit={() => { save.reset(); setEditing(c); }} />
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Modal opened={editing !== null} onClose={() => setEditing(null)}
        title={editing === "new" ? "Add connection" : "Edit connection"} size="lg">
        {save.isError && <Alert color="red" mb="sm">{save.error.message}</Alert>}
        {editing !== null && (
          <ConnectionForm key={editing === "new" ? "new" : editing.id}
            initial={editing === "new" ? undefined : editing}
            onSubmit={(v) => save.mutate(v)} submitting={save.isPending} />
        )}
      </Modal>
    </Stack>
  );
}
