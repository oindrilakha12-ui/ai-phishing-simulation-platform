"use client";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { api, ApiError, setCsrf } from "@/lib/api";
import type { SessionInfo, User } from "@/lib/types";
import { ToastProvider } from "./toast";

// ---------------------------------------------------------------- theme
type Theme = "light" | "dark";
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({ theme: "light", toggle: () => {} });

// The theme lives in localStorage (an external store), read via useSyncExternalStore so the
// server render ("light") and the client agree without effects that set state.
const themeListeners = new Set<() => void>();
function readTheme(): Theme {
  try {
    const saved = localStorage.getItem("pg-theme");
    if (saved === "dark" || saved === "light") return saved;
  } catch {}
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(
    (cb) => {
      themeListeners.add(cb);
      return () => themeListeners.delete(cb);
    },
    readTheme,
    () => "light" as Theme,
  );
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  const toggle = () => {
    try {
      localStorage.setItem("pg-theme", theme === "dark" ? "light" : "dark");
    } catch {}
    themeListeners.forEach((cb) => cb());
  };
  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

// ---------------------------------------------------------------- session
interface AuthState {
  user: User | null;
  orgName: string;
  demoMode: boolean;
  loading: boolean;
  setSession: (s: SessionInfo) => void;
  logout: () => Promise<void>;
}
const AuthCtx = createContext<AuthState | null>(null);

function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [extra, setExtra] = useState<{ orgName: string; demoMode: boolean }>(() => {
    let orgName = "";
    try {
      orgName = typeof window === "undefined" ? "" : (sessionStorage.getItem("pg-org") ?? "");
    } catch {}
    return { orgName, demoMode: true };
  });
  // On page load, the httpOnly cookie may already hold a valid session: ask /auth/me.
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
  const status = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<{ demo_mode: boolean }>("/ai/status"),
    enabled: !!me.data,
    staleTime: 300_000,
  });
  const orgs = useQuery({
    queryKey: ["org-name"],
    queryFn: () => api<{ id: string; name: string }[]>("/admin/organizations").catch(() => []),
    enabled: !!me.data && (me.data.role === "org_admin" || me.data.role === "super_admin"),
  });
  const value: AuthState = {
    user: me.data ?? null,
    orgName: extra.orgName || orgs.data?.find((o) => o.id === me.data?.org_id)?.name || "",
    demoMode: status.data?.demo_mode ?? extra.demoMode,
    loading: me.isLoading,
    setSession: (s) => {
      setCsrf(s.csrf_token);
      setExtra({ orgName: s.org_name, demoMode: s.demo_mode });
      try {
        sessionStorage.setItem("pg-org", s.org_name);
      } catch {}
      qc.setQueryData(["me"], s.user);
    },
    logout: async () => {
      await api("/auth/logout", { method: "POST" }).catch(() => undefined);
      setCsrf(null);
      try {
        sessionStorage.removeItem("pg-org");
      } catch {}
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      router.replace("/login");
    },
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

// ---------------------------------------------------------------- root
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
