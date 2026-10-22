// frontend/src/pages/LoginPage.tsx
import { Button, Card, Center, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api, errorText, type Me } from "../api";
import { ME_KEY, safeNext, useMe } from "../auth";

export function LoginPage() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api<Me>("/auth/login", { method: "POST", json: { username, password } }),
    onSuccess: (m) => { qc.clear(); qc.setQueryData(ME_KEY, m); navigate(next, { replace: true }); },
  });

  if (me.data) return <Navigate to="/" replace />;
  const submit = (e: FormEvent) => { e.preventDefault(); login.mutate(); };
  const failure = login.isError
    ? (login.error instanceof ApiError && login.error.status === 401 ? "Wrong username or password" : errorText(login.error))
    : null;

  return (
    <Center mih="80vh">
      <Card withBorder shadow="sm" padding="lg" w={360}>
        <form onSubmit={submit}>
          <Stack>
            <div>
              <Title order={3}>BankReporter</Title>
              <Text size="sm" c="dimmed">Sign in to continue</Text>
            </div>
            <TextInput label="Username" autoComplete="username" value={username}
              onChange={(e) => setUsername(e.currentTarget.value)} />
            <PasswordInput label="Password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.currentTarget.value)} />
            <Button type="submit" loading={login.isPending} disabled={!username || !password}>Sign in</Button>
            {failure && <Text c="red" size="sm">{failure}</Text>}
          </Stack>
        </form>
      </Card>
    </Center>
  );
}
