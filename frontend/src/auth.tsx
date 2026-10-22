// frontend/src/auth.tsx
import { Alert, Center, Loader } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, errorText, setUnauthorizedHandler, type Me, type Rendered } from "./api";

export const ME_KEY = ["me"];

/** Who is signed in: Me, or null when signed out. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY, retry: false, staleTime: Infinity,
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
  });
}

/** Only same-site paths: "/x" yes, "//host" or "https://host" no. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

const loginPath = (pathname: string, search: string) => `/login?next=${encodeURIComponent(pathname + search)}`;

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <Center h="60vh"><Loader /></Center>;
  if (me.isError) return <Alert color="red">{errorText(me.error)}</Alert>;
  if (!me.data) return <Navigate to={loginPath(location.pathname, location.search)} replace />;
  return <>{children}</>;
}

/** On any 401 mid-session: forget cached data and go to the login page, remembering where we were. */
export function useUnauthorizedRedirect() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const where = useRef(location);
  where.current = location;
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (where.current.pathname === "/login") return;
      qc.clear();
      navigate(loginPath(where.current.pathname, where.current.search), { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate]);
}

/**
 * A render result names the client it was made for. If that isn't the client this tab shows in its header,
 * the admin switched client in another tab (the choice lives on the shared session): refresh who we are,
 * and treat the result as stale so one client's numbers never appear under another client's name.
 */
export function useCurrentRender(rendered: Rendered | undefined): Rendered | undefined {
  const me = useMe();
  const qc = useQueryClient();
  const expected = me.data?.client?.id ?? null;
  const stale = !!rendered && rendered.client.id !== expected;
  useEffect(() => {
    if (stale) qc.invalidateQueries({ queryKey: ME_KEY });
  }, [stale, qc]);
  return stale ? undefined : rendered;
}
