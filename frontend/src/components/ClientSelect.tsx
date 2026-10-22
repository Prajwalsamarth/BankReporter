// frontend/src/components/ClientSelect.tsx
import { Alert, Anchor, Select } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api, type PublishedConnection } from "../api";

export function ClientSelect({ value, onChange, label = "Client" }: {
  value: number | null; onChange: (id: number | null) => void; label?: string;
}) {
  const clients = useQuery({ queryKey: ["published"], queryFn: () => api<PublishedConnection[]>("/connections/published") });
  useEffect(() => {
    if (value === null && clients.data?.length) onChange(clients.data[0].id);
  }, [clients.data, value, onChange]);
  if (clients.data && clients.data.length === 0) {
    return (
      <Alert color="yellow" title="No published clients">
        Map a connection and publish its views first. <Anchor component={Link} to="/">Go to Connections</Anchor>
      </Alert>
    );
  }
  return (
    <Select label={label} w={220} placeholder="Choose client" allowDeselect={false}
      data={(clients.data ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
      value={value === null ? null : String(value)} onChange={(v) => onChange(v ? Number(v) : null)} />
  );
}
