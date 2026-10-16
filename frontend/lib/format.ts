export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;

export const dt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

export const d = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const ROLE_RANK = { learner: 1, manager: 2, org_admin: 3, super_admin: 4 } as const;

export function atLeast(role: string | undefined, min: keyof typeof ROLE_RANK) {
  return !!role && (ROLE_RANK[role as keyof typeof ROLE_RANK] ?? 0) >= ROLE_RANK[min];
}
