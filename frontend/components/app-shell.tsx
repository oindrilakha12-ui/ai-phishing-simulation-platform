"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { atLeast } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Page } from "@/lib/types";
import { ErrorBoundary } from "./error-boundary";
import { useAuth, useTheme } from "./providers";
import { Badge, cx, DemoBadge, Loading } from "./ui";

type NavItem = { href: string; label: string; min: "learner" | "manager" | "org_admin"; only?: "learner" };
const NAV: NavItem[] = [
  { href: "/", label: t.nav.dashboard, min: "learner" },
  { href: "/inbox", label: t.nav.inbox, min: "learner", only: "learner" },
  { href: "/campaigns", label: t.nav.campaigns, min: "manager" },
  { href: "/templates", label: t.nav.templates, min: "manager" },
  { href: "/people", label: t.nav.people, min: "manager" },
  { href: "/training", label: t.nav.training, min: "learner" },
  { href: "/reports", label: t.nav.reports, min: "learner" },
  { href: "/reports/triage", label: t.nav.triage, min: "manager" },
  { href: "/ai", label: t.nav.ai, min: "learner" },
  { href: "/risk", label: t.nav.risk, min: "manager" },
  { href: "/admin", label: t.nav.admin, min: "org_admin" },
];

type Notif = { id: string; title: string; body: string; link: string | null; read_at: string | null; created_at: string };

function Notifications() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<Page<Notif> & { unread: number }>("/notifications", { query: { page_size: 8 } }),
    refetchInterval: 30_000,
  });
  const markAll = async () => {
    await api("/notifications/read-all", { method: "POST" });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const unread = q.data?.unread ?? 0;
  return (
    <div className="relative">
      <button
        aria-label={`Notifications, ${unread} unread`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <span aria-hidden>🔔</span>
        {unread > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-red-700 px-1.5 text-[10px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 rounded-lg border border-slate-200 bg-white p-2 shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-blue-700 dark:text-blue-400" onClick={markAll}>
              Mark all read
            </button>
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {(q.data?.items ?? []).map((n) => (
              <li key={n.id} className={cx("rounded px-2 py-2 text-sm", !n.read_at && "bg-blue-50 dark:bg-blue-950")}>
                {n.link ? (
                  <Link href={n.link} onClick={() => setOpen(false)} className="font-medium hover:underline">
                    {n.title}
                  </Link>
                ) : (
                  <span className="font-medium">{n.title}</span>
                )}
                <p className="text-xs text-slate-600 dark:text-slate-400">{n.body}</p>
              </li>
            ))}
            {q.data && q.data.items.length === 0 && <li className="px-2 py-4 text-sm text-slate-500">No notifications</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, orgName, demoMode, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname]);

  if (loading || !user) return <Loading label="Checking your session…" />;

  const items = NAV.filter((n) => atLeast(user.role, n.min) && (!n.only || user.role === n.only));
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/"));

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2">
          <button className="rounded p-2 lg:hidden" aria-label="Toggle navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
            ☰
          </button>
          <Link href="/" className="flex items-center gap-2 font-bold">
            <span aria-hidden className="rounded bg-blue-700 px-1.5 py-0.5 text-white">PG</span>
            <span>{t.appName}</span>
          </Link>
          <span className="hidden text-sm text-slate-600 sm:inline dark:text-slate-400">{orgName}</span>
          <div className="ml-auto flex items-center gap-2">
            <DemoBadge show={demoMode} />
            <Badge tone="purple" title="All learners and outcomes are synthetic">SYNTHETIC DATA</Badge>
            <Notifications />
            <button onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} className="rounded-md px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <Link href="/profile" className="hidden text-sm hover:underline md:inline">
              {user.full_name} <span className="text-slate-500">({user.role.replace("_", " ")})</span>
            </Link>
            <button onClick={logout} className="rounded-md px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
              {t.signOut}
            </button>
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-7xl gap-6 px-4">
        <nav aria-label="Main" className={cx("w-52 shrink-0 py-4 lg:block", menuOpen ? "block" : "hidden")}>
          <ul className="space-y-1">
            {items.map((n) => (
              <li key={n.href}>
                <Link
                  href={n.href}
                  aria-current={isActive(n.href) ? "page" : undefined}
                  onClick={() => setMenuOpen(false)}
                  className={cx(
                    "block rounded-md px-3 py-2 text-sm",
                    isActive(n.href) ? "bg-blue-700 font-semibold text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800",
                  )}
                >
                  {n.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" className="min-w-0 flex-1 py-6">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
