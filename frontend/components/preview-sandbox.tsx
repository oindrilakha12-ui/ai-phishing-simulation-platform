"use client";
/**
 * Email Preview Sandbox.
 *  - The lure is rendered in an <iframe srcdoc> with `sandbox="allow-same-origin"`: NO scripts, forms,
 *    popups or navigation can run. `allow-same-origin` (without allow-scripts) only lets THIS page
 *    toggle a highlight class on the <mark> cue elements; the iframe itself can execute nothing.
 *  - The document also carries its own CSP meta tag (default-src 'none').
 *  - Links were already neutralised server-side (href="#", real URL kept in data-actual-href).
 */
import { useRef, useState } from "react";
import type { Preview, RedFlag } from "@/lib/types";
import { titleCase } from "@/lib/format";
import { Badge, Button, cx } from "./ui";

export function PreviewSandbox({ preview, flags, height = 420 }: { preview: Preview; flags?: RedFlag[]; height?: number }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [active, setActive] = useState<string | null>(null);
  const [showLanding, setShowLanding] = useState(false);
  const redFlags = flags ?? preview.red_flags;

  const highlight = (id: string | null) => {
    setActive(id);
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    doc.querySelectorAll("mark.pg-active").forEach((m) => m.classList.remove("pg-active"));
    if (id) {
      const el = doc.querySelector(`mark[data-flag="${CSS.escape(id)}"]`);
      el?.classList.add("pg-active");
      el?.scrollIntoView({ block: "nearest" });
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <Badge tone="red">{preview.watermark}</Badge>
          <Button variant="secondary" onClick={() => setShowLanding((s) => !s)}>
            {showLanding ? "Show email" : "Show educational landing page"}
          </Button>
        </div>
        <iframe
          ref={frame}
          title={showLanding ? "Educational landing page (static, no inputs)" : "Sandboxed email preview"}
          sandbox="allow-same-origin"
          referrerPolicy="no-referrer"
          srcDoc={showLanding ? preview.landing_page : preview.document}
          className="w-full rounded-md border border-slate-300 bg-white dark:border-slate-600"
          style={{ height }}
        />
        {preview.links.length > 0 && (
          <div className="mt-3">
            <h3 className="mb-1 text-sm font-semibold">Inspect links</h3>
            <ul className="space-y-1 text-sm">
              {preview.links.map((l) => (
                <li key={l.index} className="rounded border border-slate-200 p-2 dark:border-slate-700">
                  <div>
                    <span className="text-slate-600 dark:text-slate-400">Displayed:</span> <code>{l.text || "(no text)"}</code>
                  </div>
                  <div>
                    <span className="text-slate-600 dark:text-slate-400">Actually goes to:</span> <code className="break-all">{l.href}</code>
                  </div>
                  {l.mismatch && (
                    <Badge tone="red">
                      Mismatch: shows {l.displayed_host}, goes to {l.actual_host}
                    </Badge>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <aside aria-label="Red flags">
        <h3 className="mb-2 text-sm font-semibold">Red flags ({redFlags.length})</h3>
        {preview.red_flags_hidden && redFlags.length === 0 ? (
          <p className="text-sm text-slate-600 dark:text-slate-400">Decide first: report it or open it. The red flags are revealed afterwards.</p>
        ) : (
          <ol className="space-y-2">
            {redFlags.map((f, i) => (
              <li key={f.id}>
                <button
                  onMouseEnter={() => highlight(f.id)}
                  onMouseLeave={() => highlight(null)}
                  onFocus={() => highlight(f.id)}
                  onBlur={() => highlight(null)}
                  aria-pressed={active === f.id}
                  className={cx(
                    "w-full rounded-md border p-2 text-left text-sm transition",
                    active === f.id ? "border-amber-500 bg-amber-50 dark:bg-amber-950" : "border-slate-200 dark:border-slate-700",
                  )}
                >
                  <span className="font-semibold">
                    {i + 1}. {titleCase(f.category)}
                  </span>
                  <span className="block text-slate-700 dark:text-slate-300">{f.description}</span>
                  {f.cue && <span className="mt-1 block text-xs text-slate-500">Cue: “{f.cue}”</span>}
                </button>
              </li>
            ))}
          </ol>
        )}
        <p className="mt-3 text-xs text-slate-500">Hover or focus a red flag to highlight it in the email.</p>
      </aside>
    </div>
  );
}
