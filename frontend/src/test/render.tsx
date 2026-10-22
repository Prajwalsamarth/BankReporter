import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

export function renderWithProviders(ui: ReactElement, { route = "/", path = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <Routes><Route path={path} element={ui} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

type Handler = (url: string, init?: RequestInit) => unknown;

/** Stub fetch with route handlers keyed "METHOD /path" (query string ignored). Records calls. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.split("?")[0];
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = `${method} ${path}`;
    if (!(key in routes)) return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 500 });
    const handler = routes[key];
    const result = typeof handler === "function" ? (handler as Handler)(url, init) : handler;
    if (result instanceof Response) return result;
    return new Response(result === undefined ? null : JSON.stringify(result), {
      status: result === undefined ? 204 : 200, headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
