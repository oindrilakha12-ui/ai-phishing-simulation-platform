"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useRef, useState, type ReactNode } from "react";
import { IndicatorList, ScoreGauge } from "@/components/indicators";
import { useAuth } from "@/components/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, DemoBadge, ErrorState, PageHeader, Select, Spinner, Tabs, Textarea } from "@/components/ui";
import { useAgentStream } from "@/hooks/use-agent-stream";
import { api } from "@/lib/api";
import { atLeast, titleCase } from "@/lib/format";
import type { Indicator } from "@/lib/types";

type TabId = "analyze" | "example" | "qa" | "coach";
type Status = { demo_mode: boolean; provider: string; vector_store: string; embedding: string; label: string };

const SAMPLE_EMAIL = `Authentication-Results: mx.globex.example; spf=fail smtp.mailfrom=paypa1-security.com; dkim=none; dmarc=fail
From: "Account Security" <alerts@paypa1-security.com>
Reply-To: support@account-verify.example
Subject: Urgent: your account will be suspended

Dear customer,

We detected unusual sign-in activity. Verify your account immediately or it will be suspended within 24 hours.

<a href="http://203.0.113.50/verify">https://www.paypal.com/security</a>
`;

function Streaming({ text, running }: { text: string; running: boolean }) {
  if (!text && !running) return null;
  return (
    <div aria-live="polite" className="whitespace-pre-wrap rounded-md bg-slate-100 p-3 text-sm dark:bg-slate-800">
      {text}
      {running && <span className="ml-1 inline-block animate-pulse">▍</span>}
    </div>
  );
}

// ---------------------------------------------------------------- Tab 1: Email Analyzer
type AnalyzeResult = {
  score: number;
  verdict: "suspicious" | "safe" | "unknown";
  indicators: Indicator[];
  explanation: string;
  demo_mode: boolean;
  links?: { displayed: string; actual: string; issues: string[] }[];
  auth_results?: Record<string, string>;
};

function AnalyzerTab() {
  const [email, setEmail] = useState("");
  const s = useAgentStream<AnalyzeResult>();
  const r = s.result?.result;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Paste an email">
        <form onSubmit={(e) => { e.preventDefault(); s.run({ kind: "analyze", text: email }); }} className="flex flex-col gap-3">
          <Textarea label="Raw email or headers + body" rows={14} maxLength={50000} value={email} onChange={(e) => setEmail(e.target.value)} hint="Treated as untrusted data. Nothing is fetched or clicked." />
          <div className="flex gap-2">
            <Button type="submit" loading={s.running} disabled={!email.trim()}>Analyze</Button>
            <Button type="button" variant="secondary" onClick={() => setEmail(SAMPLE_EMAIL)}>Load sample</Button>
          </div>
        </form>
      </Card>
      <Card title={<span className="flex items-center gap-2">Analysis {s.result && <DemoBadge show={s.result.demo_mode} />}</span>}>
        {s.error ? <ErrorState error={s.error} /> : null}
        {!s.result && !s.running && <p className="text-sm text-slate-600 dark:text-slate-400">Results appear here.</p>}
        {r && (
          <div className="mb-3 space-y-2">
            <ScoreGauge score={r.score} label="Suspicion score (rule-based)" />
            <p className="text-sm">Verdict: <Badge tone={r.verdict === "suspicious" ? "red" : r.verdict === "safe" ? "green" : "slate"}>{r.verdict}</Badge></p>
            {r.auth_results && Object.keys(r.auth_results).length > 0 && (
              <p className="text-sm">Auth results: {Object.entries(r.auth_results).map(([k, v]) => <Badge key={k} tone={v === "pass" ? "green" : "red"}>{k.toUpperCase()}={v}</Badge>)}</p>
            )}
          </div>
        )}
        <h3 className="mb-1 text-sm font-semibold">Explanation</h3>
        <Streaming text={s.text} running={s.running} />
        {r && (
          <>
            <h3 className="mb-1 mt-4 text-sm font-semibold">Indicators</h3>
            <IndicatorList indicators={r.indicators} />
            {r.links && r.links.length > 0 && (
              <>
                <h3 className="mb-1 mt-4 text-sm font-semibold">Links (displayed vs actual)</h3>
                <ul className="space-y-1 text-xs">
                  {r.links.map((l, i) => (
                    <li key={i} className="break-all rounded border border-slate-200 p-2 dark:border-slate-700">
                      <b>Shows:</b> {l.displayed} <br /><b>Goes to:</b> {l.actual} {l.issues.map((x) => <Badge key={x} tone="red">{x}</Badge>)}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- Tab 2: Training Example Viewer
type Example = {
  subject: string;
  body_text: string;
  fictional_brand: string;
  difficulty: "easy" | "medium" | "hard";
  red_flags: { category: string; description: string; cue: string }[];
  watermark: string;
  label?: string;
  validator?: { passed: boolean; problems: string[]; replaced_with_safe_default?: boolean };
};

/** Highlights red-flag cues inside plain text by building React nodes (no HTML injection). */
function HighlightedBody({ text, flags, active }: { text: string; flags: Example["red_flags"]; active: number | null }) {
  const cues = flags.map((f, i) => ({ cue: f.cue, i })).filter((c) => c.cue && text.includes(c.cue));
  const parts: ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest) {
    const next = cues.map((c) => ({ ...c, at: rest.indexOf(c.cue) })).filter((c) => c.at >= 0).sort((a, b) => a.at - b.at)[0];
    if (!next) { parts.push(rest); break; }
    parts.push(rest.slice(0, next.at));
    parts.push(<mark key={key++} className={"rounded px-0.5 " + (active === next.i ? "bg-yellow-300 outline outline-2 outline-yellow-600" : "bg-yellow-100 dark:bg-yellow-900/60")}>{next.cue}</mark>);
    rest = rest.slice(next.at + next.cue.length);
  }
  return <div className="whitespace-pre-wrap text-sm">{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</div>;
}

function ExampleTab() {
  const { user } = useAuth();
  const toast = useToast();
  const [difficulty, setDifficulty] = useState("");
  const [active, setActive] = useState<number | null>(null);
  const s = useAgentStream<Example>();
  const ex = s.result?.result;
  const canGenerate = atLeast(user?.role, "manager");
  if (!canGenerate) return <Card><p className="text-sm">The Training Example Generator is available to managers and admins.</p></Card>;
  return (
    <div className="space-y-4">
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); s.run({ kind: "generate_example", difficulty: difficulty || null }); }} className="flex flex-wrap items-end gap-3">
          <Select label="Difficulty" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
            <option value="">Any</option><option>easy</option><option>medium</option><option>hard</option>
          </Select>
          <Button type="submit" loading={s.running}>Generate fictional training example</Button>
          <p className="text-xs text-slate-600 dark:text-slate-400">Fictional brands only · always watermarked · validated before display.</p>
        </form>
      </Card>
      {s.error ? <ErrorState error={s.error} /> : null}
      {s.running && !ex && <Streaming text={s.text} running />}
      {ex && (
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <Card title={<span className="flex flex-wrap items-center gap-2">Example email {s.result?.demo_mode && <DemoBadge />} {ex.label && <Badge tone="amber">{ex.label}</Badge>}</span>}>
            <div className="rounded-md border border-slate-300 dark:border-slate-600">
              <div className="bg-red-700 px-3 py-1 text-center text-xs font-bold tracking-wide text-white">{ex.watermark}</div>
              <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800">
                <div><b>Brand:</b> {ex.fictional_brand} (fictional) · <Badge>{ex.difficulty}</Badge></div>
                <div><b>Subject:</b> {ex.subject}</div>
              </div>
              <div className="p-3"><HighlightedBody text={ex.body_text} flags={ex.red_flags} active={active} /></div>
            </div>
            {ex.validator && (
              <p className="mt-2 text-xs">
                Validator: {ex.validator.passed ? <Badge tone="green">passed</Badge> : <Badge tone="red">rejected → safe default shown ({ex.validator.problems.join(", ")})</Badge>}
              </p>
            )}
            <Button
              variant="secondary"
              className="mt-3"
              onClick={async () => {
                try {
                  const r = await api<{ name: string }>("/ai/generate/save", { method: "POST", body: { subject: ex.subject, body_text: ex.body_text, fictional_brand: ex.fictional_brand, difficulty: ex.difficulty, red_flags: ex.red_flags } });
                  toast.push("success", `Saved as template “${r.name}”`);
                } catch (e) {
                  toast.error(e);
                }
              }}
            >
              Save as campaign template
            </Button>
          </Card>
          <Card title="Red flags">
            <ol className="space-y-2">
              {ex.red_flags.map((f, i) => (
                <li key={i}>
                  <button onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(i)} onBlur={() => setActive(null)} className="w-full rounded border border-slate-200 p-2 text-left text-sm dark:border-slate-700">
                    <b>{i + 1}. {titleCase(f.category)}</b>
                    <span className="block">{f.description}</span>
                  </button>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Tab 3: Knowledge Q&A
type QAResult = { answer: string; sources?: { title: string; chunk_preview: string; similarity: number }[]; refused?: boolean; mode?: string; demo_mode: boolean };
type Msg = { role: "user" | "assistant"; text: string; result?: QAResult; demo?: boolean; routed?: string };

function QATab() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [useRouter_, setUseRouter] = useState(false);
  const session = useRef(crypto.randomUUID().replace(/-/g, ""));
  const s = useAgentStream<QAResult>();

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    setMessages((m) => [...m, { role: "user", text: q }]);
    setInput("");
    const out = await s.run({ kind: useRouter_ ? "chat" : "qa", text: q, session_id: session.current });
    if (out) {
      const r = out.result;
      const text = r.answer ?? (r as unknown as { explanation?: string }).explanation ?? "(see the other tabs for this kind of result)";
      setMessages((m) => [...m, { role: "assistant", text, result: r, demo: out.demo_mode, routed: out.request_type }]);
    }
  };

  return (
    <Card>
      <div className="mb-3 max-h-[28rem] space-y-3 overflow-y-auto" aria-live="polite">
        {messages.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-400">Ask about reporting, MFA, passwords, BEC, smishing/vishing or QR-code phishing. Answers come only from the knowledge base, with sources.</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-auto max-w-[80%] rounded-lg bg-blue-700 p-3 text-sm text-white" : "max-w-[90%] rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800"}>
            {m.role === "assistant" && (
              <div className="mb-1 flex flex-wrap gap-2">
                <DemoBadge show={!!m.demo} />
                {m.result?.mode === "retrieval_only" && <Badge tone="blue">retrieval-only</Badge>}
                {m.result?.refused && <Badge tone="red">refused (out of scope)</Badge>}
                {m.routed && useRouter_ && <Badge>router → {m.routed}</Badge>}
              </div>
            )}
            <p className="whitespace-pre-wrap">{m.text}</p>
            {m.result?.sources && m.result.sources.length > 0 && (
              <div className="mt-2 border-t border-slate-300 pt-2 text-xs dark:border-slate-600">
                <b>Sources</b>
                <ul>{m.result.sources.map((src, j) => <li key={j}>[{src.title}] <span className="text-slate-500">— “{src.chunk_preview.slice(0, 100)}…” (sim {src.similarity})</span></li>)}</ul>
              </div>
            )}
          </div>
        ))}
        {s.running && <div className="max-w-[90%] rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800"><Streaming text={s.text} running /></div>}
      </div>
      {s.error ? <ErrorState error={s.error} /> : null}
      <form onSubmit={ask} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Textarea label="Your question" rows={2} maxLength={1000} value={input} onChange={(e) => setInput(e.target.value)} />
        </div>
        <Button type="submit" loading={s.running}>Ask</Button>
      </form>
      <label className="mt-2 flex items-center gap-2 text-xs">
        <input type="checkbox" checked={useRouter_} onChange={(e) => setUseRouter(e.target.checked)} />
        Free-text mode: send through the agent router (it may route to another agent, or refuse out-of-scope requests)
      </label>
    </Card>
  );
}

// ---------------------------------------------------------------- Tab 4: Awareness Coach
type CoachResult = { tips: { title: string; body: string; category: string }[]; based_on: { weak_categories: string[]; completion_rate: number | null; simulated_clicks: number }; demo_mode: boolean };

function CoachTab() {
  const s = useAgentStream<CoachResult>();
  const r = s.result?.result;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => s.run({ kind: "coach" })} loading={s.running}>Get my tips</Button>
          <p className="text-sm text-slate-600 dark:text-slate-400">Based on your synthetic history: missed red-flag categories and training completion.</p>
        </div>
      </Card>
      {s.error ? <ErrorState error={s.error} /> : null}
      {s.running && <Streaming text={s.text} running />}
      {r && (
        <>
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <DemoBadge show={s.result!.demo_mode} /> Weakest areas: {r.based_on.weak_categories.map((c) => <Badge key={c} tone="amber">{titleCase(c)}</Badge>)}
            · Completion: {r.based_on.completion_rate == null ? "—" : `${Math.round(r.based_on.completion_rate * 100)}%`}
          </p>
          <div className="grid gap-4 md:grid-cols-3">
            {r.tips.map((t, i) => (
              <Card key={i} title={t.title}>
                <p className="text-sm">{t.body}</p>
                <p className="mt-2"><Badge tone="blue">{titleCase(t.category)}</Badge></p>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- page
function Studio() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as TabId) || "analyze";
  const status = useQuery({ queryKey: ["ai-status-full"], queryFn: () => api<Status>("/ai/status") });
  const tabs: { id: TabId; label: string }[] = [
    { id: "analyze", label: "Email Analyzer" },
    { id: "example", label: "Training Example Viewer" },
    { id: "qa", label: "Knowledge Q&A" },
    { id: "coach", label: "Awareness Coach" },
  ];
  return (
    <>
      <PageHeader
        title="AI Studio"
        subtitle={
          status.data ? (
            <span className="flex flex-wrap items-center gap-2">
              <DemoBadge show={status.data.demo_mode} /> {status.data.label} · vector store: {status.data.vector_store} · {status.data.embedding}
            </span>
          ) : <Spinner small />
        }
      />
      {status.data?.demo_mode && (
        <p className="mb-4 rounded-md border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          DEMO MODE: no AI provider key is configured, so the analyzer adds a canned explanation (labelled), the coach picks from a tips library,
          Q&A returns the best retrieved passage without rewriting, and the generator returns one of five pre-written fictional examples.
        </p>
      )}
      <Tabs label="AI Studio tools" tabs={tabs} value={tab} onChange={(t) => router.replace(`/ai?tab=${t}`)} />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "analyze" && <AnalyzerTab />}
        {tab === "example" && <ExampleTab />}
        {tab === "qa" && <QATab />}
        {tab === "coach" && <CoachTab />}
      </div>
    </>
  );
}

export default function AIStudioPage() {
  return (
    <Suspense>
      <Studio />
    </Suspense>
  );
}
