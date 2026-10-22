// frontend/src/components/UserMenu.tsx
import { Badge, Button, Group, Select, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type Me } from "../api";
import { ME_KEY, useMe } from "../auth";

const NONE = "none";

export function UserMenu() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const switchClient = useMutation({
    mutationFn: (id: number | null) => api<Me>("/auth/me/client", { method: "PUT", json: { client_id: id } }),
    onSuccess: (m) => {
      qc.setQueryData(ME_KEY, m);
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
    },
  });
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => { qc.clear(); qc.setQueryData(ME_KEY, null); navigate("/login", { replace: true }); },
  });
  if (!me.data) return null;
  const { user, client, clients } = me.data;
  return (
    <Group gap="sm" ml="auto" wrap="nowrap">
      {user.role === "admin" ? (
        <Select aria-label="Client" size="xs" w={200} allowDeselect={false}
          data={[{ value: NONE, label: "— none —" }, ...clients.map((c) => ({ value: String(c.id), label: c.name }))]}
          value={client ? String(client.id) : NONE}
          onChange={(v) => switchClient.mutate(v && v !== NONE ? Number(v) : null)} />
      ) : (
        client && <Badge variant="light" size="lg">{client.name}</Badge>
      )}
      <Text size="sm">{user.display_name}</Text>
      <Button size="xs" variant="default" onClick={() => logout.mutate()} loading={logout.isPending}>Sign out</Button>
    </Group>
  );
}
