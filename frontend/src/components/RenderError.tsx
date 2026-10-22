// frontend/src/components/RenderError.tsx
import { Alert, Anchor } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api, errorText, type Connection } from "../api";
import { useMe } from "../auth";

function NotPublished() {
  const me = useMe();
  const connections = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections") });
  const own = connections.data?.find((c) => c.client?.id === me.data?.client?.id);
  return (
    <Alert color="yellow" title="Your data mapping isn't published yet" className="no-print">
      {own
        ? <Anchor component={Link} to={`/connections/${own.id}/mapping`}>Open the mapping</Anchor>
        : "Ask the platform admin to set up your connection."}
    </Alert>
  );
}

export function RenderError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 409 && errorText(error).includes("no published views")) {
    return <NotPublished />;
  }
  return <Alert color="red" className="no-print">{errorText(error)}</Alert>;
}
