// frontend/src/components/OwnerBadge.tsx
import { Badge } from "@mantine/core";
import type { Ownership } from "../api";

export function OwnerBadge({ item }: { item: Ownership }) {
  return item.shared
    ? <Badge variant="light" color="gray">Shared</Badge>
    : <Badge variant="light" color="blue">Private</Badge>;
}
