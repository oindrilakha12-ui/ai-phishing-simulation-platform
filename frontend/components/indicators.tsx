"use client";
import type { Indicator } from "@/lib/types";
import { Badge } from "./ui";

const TONE = { high: "red", medium: "amber", low: "slate" } as const;

/** Highlighted list of indicators from the Indicator Analyst (heuristic + optional LLM note). */
export function IndicatorList({ indicators }: { indicators: Indicator[] }) {
  if (!indicators.length) return <p className="text-sm text-slate-600 dark:text-slate-400">No rule-based indicators fired.</p>;
  return (
    <ul className="space-y-2">
      {indicators.map((i) => (
        <li key={i.id} className={"rounded-md border-l-4 bg-white p-3 text-sm dark:bg-slate-900 " + (i.severity === "high" ? "border-red-600" : i.severity === "medium" ? "border-amber-500" : "border-slate-400")}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={TONE[i.severity]}>{i.severity}</Badge>
            <span className="font-semibold">{i.title}</span>
          </div>
          <p className="mt-1">{i.explanation}</p>
          {i.evidence && <p className="mt-1 break-all text-xs text-slate-600 dark:text-slate-400">Evidence: <code>{i.evidence}</code></p>}
          {i.llm_note && <p className="mt-1 text-xs italic">AI note: {i.llm_note}</p>}
        </li>
      ))}
    </ul>
  );
}

export function ScoreGauge({ score, label }: { score: number; label: string }) {
  const color = score >= 45 ? "bg-red-600" : score >= 20 ? "bg-amber-500" : "bg-green-600";
  return (
    <div>
      <div className="flex justify-between text-sm"><span>{label}</span><b>{score}/100</b></div>
      <div className="mt-1 h-3 rounded bg-slate-200 dark:bg-slate-700" role="meter" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`h-3 rounded ${color}`} style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}
