// frontend/src/App.test.tsx
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { safeNext } from "./auth";
import { meAdmin, meClient } from "./test/fixtures";
import { mockApi } from "./test/render";

const unauthorized = () => new Response(JSON.stringify({ detail: "Sign in to continue" }), { status: 401 });

function renderApp(route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider><QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}><App /></MemoryRouter>
    </QueryClientProvider></MantineProvider>,
  );
}

describe("sign-in", () => {
  it("sends a signed-out visitor to the login page and back after signing in", async () => {
    let signedIn = false;
    const calls = mockApi({
      "GET /api/auth/me": () => (signedIn ? meClient : unauthorized()),
      "POST /api/auth/login": () => { signedIn = true; return meClient; },
      "GET /api/reports": [],
    });
    renderApp("/reports");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "nova.analyst");
    await user.type(screen.getByLabelText("Password"), "nova123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/auth/login")?.body).toEqual({ username: "nova.analyst", password: "nova123" });
    expect(screen.getByText("NovaBank")).toBeInTheDocument();
  });

  it("shows the generic error for a wrong password", async () => {
    mockApi({
      "GET /api/auth/me": unauthorized,
      "POST /api/auth/login": () => new Response(JSON.stringify({ detail: "Wrong username or password" }), { status: 401 }),
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "x");
    await user.type(screen.getByLabelText("Password"), "y");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Wrong username or password")).toBeInTheDocument();
  });

  it("returns to the login page when the session expires mid-use", async () => {
    let expired = false;
    mockApi({
      "GET /api/auth/me": () => (expired ? unauthorized() : meClient),
      "GET /api/connections": () => { expired = true; return unauthorized(); },
    });
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("only follows same-site next paths", () => {
    expect(safeNext("/reports")).toBe("/reports");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});

describe("header", () => {
  it("lets the admin switch client and sign out", async () => {
    const calls = mockApi({
      "GET /api/auth/me": meAdmin,
      "GET /api/connections": [],
      "PUT /api/auth/me/client": { ...meAdmin, client: meAdmin.clients[0] },
      "POST /api/auth/logout": undefined,
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("textbox", { name: "Client" }));
    await user.click(await screen.findByRole("option", { name: "Bharat Finserv" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/auth/me/client")?.body).toEqual({ client_id: 2 }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/connections").length).toBeGreaterThan(1));   // refetched
    expect(screen.getByText("Platform Admin")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/auth/logout")).toBe(true));
  });
});
