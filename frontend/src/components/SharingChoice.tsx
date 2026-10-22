// frontend/src/components/SharingChoice.tsx
import { Group, Radio } from "@mantine/core";
import { useMe } from "../auth";

/** Admin only: a new item is shared with every client or private to the selected one. */
export function SharingChoice({ shared, onChange }: { shared: boolean; onChange: (shared: boolean) => void }) {
  const me = useMe();
  if (me.data?.user.role !== "admin") return null;
  const client = me.data.client;
  return (
    <Radio.Group label="Who can see it" value={shared ? "shared" : "private"} onChange={(v) => onChange(v === "shared")}>
      <Group mt={4}>
        <Radio value="shared" label="Shared with all clients" />
        <Radio value="private" label={`Only ${client?.name ?? "the selected client"}`} disabled={!client} />
      </Group>
    </Radio.Group>
  );
}
