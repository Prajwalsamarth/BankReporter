import { Button, Group, PasswordInput, SegmentedControl, Select, Stack, TagsInput, Text, TextInput } from "@mantine/core";
import { useState, type FormEvent } from "react";
import type { ClientRef, Connection, ConnectionInput, Dialect } from "../api";

const DEFAULT_PORT: Record<Dialect, number> = { postgresql: 5432, mysql: 3306 };

/** host/port/database/user from a masked URL like postgresql+psycopg://user:***@host:5433/db */
function parseMaskedUrl(url: string | null) {
  const m = url?.match(/^[^:]+:\/\/([^:@/]+)(?::[^@]*)?@([^:/]+)(?::(\d+))?\/(.*)$/);
  return m ? { user: m[1], host: m[2], port: m[3] ?? "", database: m[4] } : null;
}

interface Props {
  initial?: Connection;
  onSubmit: (values: ConnectionInput) => void;
  submitting?: boolean;
  clients?: ClientRef[];     // admin only: which client the connection belongs to
}

export function ConnectionForm({ initial, onSubmit, submitting, clients }: Props) {
  const parsed = parseMaskedUrl(initial?.url_masked ?? null);
  const [values, setValues] = useState({
    name: initial?.name ?? "",
    dialect: (initial?.dialect ?? "postgresql") as Dialect,
    host: parsed?.host ?? "localhost",
    port: parsed?.port ?? String(DEFAULT_PORT[initial?.dialect ?? "postgresql"]),
    database: parsed?.database ?? "",
    user: parsed?.user ?? "",
    password: "",
    schemas: initial?.schemas ?? [],
    client: initial?.client ? String(initial.client.id) : (null as string | null),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof values) => (v: unknown) => setValues((s) => ({ ...s, [k]: v }));

  function changeDialect(d: string) {
    const dialect = d as Dialect;
    setValues((s) => ({
      ...s, dialect,
      port: s.port === String(DEFAULT_PORT[s.dialect]) ? String(DEFAULT_PORT[dialect]) : s.port,
    }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    for (const k of ["name", "host", "database", "user"] as const) if (!values[k].trim()) errs[k] = "Required";
    if (!/^\d+$/.test(values.port)) errs.port = "Port must be a number";
    if (!initial && !values.password) errs.password = "Password is required";
    if (values.schemas.length === 0) errs.schemas = "Add at least one schema";
    if (clients && !values.client) errs.client = "Choose a client";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    onSubmit({
      name: values.name.trim(), dialect: values.dialect, host: values.host.trim(), port: Number(values.port),
      database: values.database.trim(), user: values.user.trim(),
      password: values.password ? values.password : null, schemas: values.schemas,
      ...(clients ? { client_id: Number(values.client) } : {}),
    });
  }

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        {clients && (
          <Select label="Client" placeholder="Choose client" allowDeselect={false} value={values.client}
            data={clients.map((c) => ({ value: String(c.id), label: c.name }))}
            onChange={(v) => set("client")(v)} error={errors.client} />
        )}
        <TextInput label="Name" value={values.name} onChange={(e) => set("name")(e.currentTarget.value)} error={errors.name} />
        <div>
          <Text size="sm" fw={500} mb={4}>Database type</Text>
          <SegmentedControl value={values.dialect} onChange={changeDialect}
            data={[{ value: "postgresql", label: "PostgreSQL" }, { value: "mysql", label: "MySQL" }]} />
        </div>
        <Group grow align="flex-start">
          <TextInput label="Host" value={values.host} onChange={(e) => set("host")(e.currentTarget.value)} error={errors.host} />
          <TextInput label="Port" inputMode="numeric" value={values.port}
            onChange={(e) => set("port")(e.currentTarget.value)} error={errors.port} />
        </Group>
        <TextInput label="Database" value={values.database} onChange={(e) => set("database")(e.currentTarget.value)} error={errors.database} />
        <Group grow align="flex-start">
          <TextInput label="User" value={values.user} onChange={(e) => set("user")(e.currentTarget.value)} error={errors.user} />
          <PasswordInput label="Password" value={values.password} autoComplete="new-password"
            placeholder={initial ? "leave blank to keep" : undefined}
            onChange={(e) => set("password")(e.currentTarget.value)} error={errors.password} />
        </Group>
        <TagsInput label="Schemas" description="Schemas to scan; press Enter after each" value={values.schemas}
          onChange={set("schemas")} error={errors.schemas} />
        <Group justify="flex-end"><Button type="submit" loading={submitting}>Save</Button></Group>
      </Stack>
    </form>
  );
}
