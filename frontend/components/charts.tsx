"use client";
/**
 * Analytics charts (Recharts). Each chart has an accessible text alternative (a visually hidden
 * data table) so screen-reader users get the same information.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { pct, titleCase } from "@/lib/format";
import type { Overview } from "@/lib/types";

const CLICK = "#b91c1c";
const REPORT = "#1d4ed8";
const asPct = (v: number) => `${Math.round(v * 100)}%`;

function SrTable({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>{head.map((h) => <th key={h}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

export function TrendChart({ data }: { data: Overview["trend"] }) {
  return (
    <figure>
      <div className="h-64" aria-hidden>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ left: -10, right: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="week" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={asPct} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => asPct(Number(v))} />
            <Legend />
            <Line type="monotone" dataKey="click_rate" name="Click rate" stroke={CLICK} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="report_rate" name="Report rate" stroke={REPORT} strokeWidth={2} strokeDasharray="5 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <SrTable caption="Weekly click and report rates" head={["Week", "Click rate", "Report rate"]} rows={data.map((d) => [d.week, pct(d.click_rate), pct(d.report_rate)])} />
    </figure>
  );
}

export function DepartmentBars({ data }: { data: Overview["departments"] }) {
  return (
    <figure>
      <div className="h-64" aria-hidden>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="department" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={50} />
            <YAxis tickFormatter={asPct} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => asPct(Number(v))} />
            <Legend />
            <Bar dataKey="click_rate" name="Click rate" fill={CLICK} />
            <Bar dataKey="report_rate" name="Report rate" fill={REPORT} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <SrTable caption="Click and report rate by department" head={["Department", "Click rate", "Report rate"]} rows={data.map((d) => [d.department, pct(d.click_rate), pct(d.report_rate)])} />
    </figure>
  );
}

export function FlagBars({ data }: { data: Overview["top_failed_flags"] }) {
  const rows = data.slice(0, 8).map((d) => ({ ...d, label: titleCase(d.category) }));
  return (
    <figure>
      <div className="h-64" aria-hidden>
        <ResponsiveContainer>
          <BarChart data={rows} layout="vertical" margin={{ left: 30 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="label" tick={{ fontSize: 11 }} width={90} />
            <Tooltip />
            <Bar dataKey="count" name="Simulated clicks" fill="#b45309" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <SrTable caption="Most-missed red-flag categories" head={["Category", "Clicks"]} rows={rows.map((r) => [r.label, r.count])} />
    </figure>
  );
}

export function CohortBars({ data }: { data: Overview["cohorts"] }) {
  return (
    <figure>
      <div className="h-56" aria-hidden>
        <ResponsiveContainer>
          <BarChart data={data.map((c) => ({ ...c, label: titleCase(c.cohort) }))} margin={{ left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={asPct} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => asPct(Number(v))} />
            <Legend />
            <Bar dataKey="click_rate" name="Click rate" fill={CLICK} />
            <Bar dataKey="report_rate" name="Report rate" fill={REPORT} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <SrTable caption="Cohort comparison by difficulty" head={["Difficulty", "Click rate", "Report rate"]} rows={data.map((c) => [c.cohort, pct(c.click_rate), pct(c.report_rate)])} />
    </figure>
  );
}

/** Department × month click-rate heatmap (pure CSS grid; colour + number for colour-blind users). */
export function Heatmap({ data }: { data: Overview["heatmap"] }) {
  const months = [...new Set(data.map((d) => d.month))].sort();
  const depts = [...new Set(data.map((d) => d.department))].sort();
  const cell = (dept: string, m: string) => data.find((d) => d.department === dept && d.month === m);
  const shade = (v: number) => {
    const a = Math.min(1, v / 0.4);
    return `rgba(185, 28, 28, ${0.08 + a * 0.85})`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <caption className="sr-only">Click rate heatmap by department and month</caption>
        <thead>
          <tr>
            <th scope="col" className="p-1 text-left">Department</th>
            {months.map((m) => (
              <th key={m} scope="col" className="p-1">{m}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {depts.map((dep) => (
            <tr key={dep}>
              <th scope="row" className="p-1 pr-3 text-left font-medium">{dep}</th>
              {months.map((m) => {
                const c = cell(dep, m);
                return (
                  <td
                    key={m}
                    className="min-w-14 p-2 text-center font-semibold"
                    style={{ background: c ? shade(c.click_rate) : undefined, color: c && c.click_rate > 0.22 ? "white" : undefined }}
                    title={c ? `${dep} ${m}: ${pct(c.click_rate)} of ${c.recipients}` : "no data"}
                  >
                    {c ? pct(c.click_rate, 0) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
