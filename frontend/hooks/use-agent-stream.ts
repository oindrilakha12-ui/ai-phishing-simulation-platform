"use client";
import { useCallback, useRef, useState } from "react";
import { streamSSE } from "@/lib/api";
import type { AgentOutput } from "@/lib/types";

/** Runs one AI Studio request over SSE: collects streamed text and the final structured result. */
export function useAgentStream<R = Record<string, unknown>>() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<AgentOutput<R> | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);

  /** Resolves with the final structured result (or null on error/abort). */
  const run = useCallback(async (body: Record<string, unknown>): Promise<AgentOutput<R> | null> => {
    abort.current?.abort();
    abort.current = new AbortController();
    setText("");
    setResult(null);
    setError(null);
    setRunning(true);
    let final: AgentOutput<R> | null = null;
    try {
      await streamSSE(
        "/ai/stream",
        body,
        (event, data) => {
          if (event === "token") setText((t) => t + (data as { text: string }).text);
          if (event === "result") {
            final = data as AgentOutput<R>;
            setResult(final);
          }
        },
        abort.current.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(e);
    } finally {
      setRunning(false);
    }
    return final;
  }, []);

  return { text, result, running, error, run, stop: () => abort.current?.abort() };
}
