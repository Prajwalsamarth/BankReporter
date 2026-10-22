// frontend/src/App.tsx
import { AppShell, Group, NavLink as MantineNavLink, Title } from "@mantine/core";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { RequireAuth, useUnauthorizedRedirect } from "./auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { UserMenu } from "./components/UserMenu";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DashboardsPage } from "./pages/DashboardsPage";
import { LoginPage } from "./pages/LoginPage";
import { MappingPage } from "./pages/MappingPage";
import { ReportEditorPage } from "./pages/ReportEditorPage";
import { ReportsPage } from "./pages/ReportsPage";

const NAV = [{ to: "/", label: "Connections", end: true }, { to: "/reports", label: "Reports" }, { to: "/dashboards", label: "Dashboards" }];

function Shell() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header className="no-print">
        <Group h="100%" px="md" gap="lg" wrap="nowrap">
          <Title order={3}><Link to="/" style={{ color: "inherit", textDecoration: "none" }}>BankReporter</Link></Title>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} style={{ textDecoration: "none" }}>
              {({ isActive }) => <MantineNavLink component="span" label={n.label} active={isActive} w="auto" />}
            </NavLink>
          ))}
          <UserMenu />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<ConnectionsPage />} />
            <Route path="/connections/:id/mapping" element={<MappingPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/reports/new" element={<ReportEditorPage />} />
            <Route path="/reports/:id/edit" element={<ReportEditorPage />} />
            <Route path="/dashboards" element={<DashboardsPage />} />
            <Route path="/dashboards/:id" element={<DashboardsPage />} />
          </Routes>
        </ErrorBoundary>
      </AppShell.Main>
    </AppShell>
  );
}

export function App() {
  useUnauthorizedRedirect();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<RequireAuth><Shell /></RequireAuth>} />
    </Routes>
  );
}
