import { AppShell, Group, NavLink as MantineNavLink, Title } from "@mantine/core";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DashboardsPage } from "./pages/DashboardsPage";
import { MappingPage } from "./pages/MappingPage";
import { ReportEditorPage } from "./pages/ReportEditorPage";
import { ReportsPage } from "./pages/ReportsPage";

const NAV = [{ to: "/", label: "Connections", end: true }, { to: "/reports", label: "Reports" }, { to: "/dashboards", label: "Dashboards" }];

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header className="no-print">
        <Group h="100%" px="md" gap="lg">
          <Title order={3}><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>BankReporter</Link></Title>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} style={{ textDecoration: "none" }}>
              {({ isActive }) => <MantineNavLink component="span" label={n.label} active={isActive} w="auto" />}
            </NavLink>
          ))}
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<ConnectionsPage />} />
          <Route path="/connections/:id/mapping" element={<MappingPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/new" element={<ReportEditorPage />} />
          <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
          <Route path="/dashboards" element={<DashboardsPage />} />
          <Route path="/dashboards/:id" element={<DashboardsPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}
