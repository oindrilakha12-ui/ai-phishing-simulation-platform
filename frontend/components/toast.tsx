"use client";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";

type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
const Ctx = createContext<{ push: (kind: Toast["kind"], text: string) => void; error: (e: unknown) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  const error = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError) {
        const details = Array.isArray(e.details) ? `: ${e.details.map((d) => (typeof d === "string" ? d : d?.msg)).join("; ")}` : "";
        push("error", `${e.message}${details}`);
      } else push("error", e instanceof Error ? e.message : "Something went wrong");
    },
    [push],
  );
  return (
    <Ctx.Provider value={{ push, error }}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={
              "rounded-md px-4 py-3 text-sm shadow-lg " +
              (t.kind === "error" ? "bg-red-700 text-white" : t.kind === "success" ? "bg-green-700 text-white" : "bg-slate-800 text-white")
            }
          >
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useToast outside ToastProvider");
  return c;
}
