"use client";

export type PineBar = { t: number; o: number; h: number; l: number; c: number; v: number | null };
export type PinePlot =
  | { kind: "line"; title: string; overlay: boolean; hidden: boolean; color: string; data: [number, number, string | null][] }
  | { kind: "hline"; title: string; value: number; color: string }
  | { kind: "fill"; title: string; plot1: string; plot2: string; color: string };
export type PineResult =
  | { ok: true; title: string; overlay: boolean; plots: PinePlot[]; warnings: string[] }
  | { ok: false; error: string };

const TIMEOUT_MS = 10_000;
let worker: Worker | null = null;
let seq = 0;

function getWorker(): Worker {
  // Separate file with its own CSP (see infra/caddy/Caddyfile); no network access inside.
  worker ??= new Worker("/pine-worker.js");
  return worker;
}

/** Runs one script; a hung script is killed after 10 s (worker is recreated). Runs are serialised. */
let queue: Promise<unknown> = Promise.resolve();

export function runPine(source: string, bars: PineBar[], tf: "1d" | "1w"): Promise<PineResult> {
  const job = queue.then(
    () =>
      new Promise<PineResult>((resolve) => {
        const w = getWorker();
        const id = ++seq;
        const timer = setTimeout(() => {
          w.terminate();
          worker = null;
          resolve({ ok: false, error: "Timeout: Skript lief länger als 10 s und wurde abgebrochen" });
        }, TIMEOUT_MS);
        const onMsg = (e: MessageEvent<{ id: number } & PineResult>) => {
          if (e.data.id !== id) return;
          clearTimeout(timer);
          w.removeEventListener("message", onMsg);
          resolve(e.data);
        };
        w.addEventListener("message", onMsg);
        w.onerror = (ev) => {
          clearTimeout(timer);
          worker = null;
          resolve({ ok: false, error: `Worker-Fehler: ${ev.message || "unbekannt"}` });
        };
        w.postMessage({ id, source, bars, tf });
      }),
  );
  queue = job.catch(() => undefined);
  return job;
}
