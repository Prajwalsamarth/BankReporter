import { AppShell, Group, Title } from "@mantine/core";
import { Link, Route, Routes } from "react-router-dom";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { MappingPage } from "./pages/MappingPage";

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md">
          <Title order={3}><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>BankReporter</Link></Title>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<ConnectionsPage />} />
          <Route path="/connections/:id/mapping" element={<MappingPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}
