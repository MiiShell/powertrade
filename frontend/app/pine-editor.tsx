"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { api, type PineScript } from "./api";
import { runPine, type PineBar } from "./pine-client";

const TEMPLATE = `//@version=5
indicator("Mein Indikator", overlay=false)
len = input.int(14, "Länge")
r = ta.rsi(close, len)
plot(r, color=color.purple, title="RSI")
hline(70)
hline(30)
`;

type Draft = { id: number | null; name: string; source: string; builtin: boolean };

export function PineEditor({ bars, tf, onClose, onSaved }: {
  bars: PineBar[]; tf: "1d" | "1w"; onClose: () => void; onSaved: (id: number) => void;
}) {
  const [scripts, setScripts] = useState<PineScript[]>([]);
  const [draft, setDraft] = useState<Draft>({ id: null, name: "Mein Indikator", source: TEMPLATE, builtin: false });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    void api.pineScripts().then((r) => setScripts(r.data?.scripts ?? []));
  }, [version]);

  const open = (s: PineScript) => {
    setDraft({ id: s.id, name: s.name, source: s.source, builtin: s.builtin });
    setMsg(null);
    setConfirmDelete(false);
  };

  async function test() {
    setMsg({ ok: true, text: "Läuft…" });
    const r = await runPine(draft.source, bars, tf);
    if (!r.ok) return setMsg({ ok: false, text: r.error });
    const lines = r.plots.filter((p) => p.kind === "line").length;
    const warn = r.warnings.length ? ` · Warnungen: ${r.warnings.join("; ")}` : "";
    setMsg({ ok: true, text: `OK: „${r.title}“ · ${lines} Plot(s) · ${r.overlay ? "im Preis-Chart" : "eigener Bereich"}${warn}` });
  }

  async function save(asCopy = false) {
    const body = { name: asCopy ? `${draft.name} (Kopie)` : draft.name, source: draft.source };
    const r = draft.id && !asCopy && !draft.builtin ? await api.updatePine(draft.id, body) : await api.createPine(body);
    if (r.status >= 300 || !r.data) {
      const detail = (r.data as unknown as { detail?: unknown } | null)?.detail;
      return setMsg({ ok: false, text: `Speichern fehlgeschlagen (${r.status}): ${typeof detail === "string" ? detail : JSON.stringify(detail ?? "")}` });
    }
    setDraft({ id: r.data.id, name: r.data.name, source: r.data.source, builtin: r.data.builtin });
    setMsg({ ok: true, text: "Gespeichert und im Chart aktiviert" });
    setVersion((v) => v + 1);
    onSaved(r.data.id);
  }

  async function remove() {
    if (!draft.id) return;
    if (!confirmDelete) return setConfirmDelete(true);
    const r = await api.deletePine(draft.id);
    if (r.status !== 204) return setMsg({ ok: false, text: `Löschen fehlgeschlagen (${r.status})` });
    setDraft({ id: null, name: "Mein Indikator", source: TEMPLATE, builtin: false });
    setConfirmDelete(false);
    setMsg({ ok: true, text: "Gelöscht" });
    setVersion((v) => v + 1);
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const el = e.currentTarget;
    const { selectionStart: s, selectionEnd: t } = el;
    const next = draft.source.slice(0, s) + "    " + draft.source.slice(t);
    setDraft({ ...draft, source: next });
    requestAnimationFrame(() => el.setSelectionRange(s + 4, s + 4));
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Pine-Script-Editor">
      <div className="modal">
        <div className="row wrap">
          <h2>Pine-Script-Editor</h2>
          <button className="secondary small" onClick={onClose} aria-label="Schließen">✕</button>
        </div>
        <div className="editor-grid">
          <aside className="script-list">
            <button className="small" onClick={() => { setDraft({ id: null, name: "Mein Indikator", source: TEMPLATE, builtin: false }); setMsg(null); }}>+ Neu</button>
            {scripts.map((s) => (
              <button key={s.id} className={`link script-item${draft.id === s.id ? " on" : ""}`} onClick={() => open(s)}>
                {s.name} {s.builtin && <span className="badge">built-in</span>}
              </button>
            ))}
          </aside>
          <div className="editor-main">
            <input value={draft.name} maxLength={80} aria-label="Name" disabled={draft.builtin}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <textarea className="code" value={draft.source} spellCheck={false} readOnly={draft.builtin} onKeyDown={onKey}
              aria-label="Pine Script Quelltext" onChange={(e) => setDraft({ ...draft, source: e.target.value })} />
            {draft.builtin && <p className="muted small">Built-in-Skripte sind schreibgeschützt – „Duplizieren“ zum Bearbeiten.</p>}
            <div className="row gap">
              <button className="secondary small" onClick={test}>▶ Testen</button>
              {!draft.builtin && <button className="small" onClick={() => void save()}>Speichern</button>}
              {draft.id !== null && <button className="secondary small" onClick={() => void save(true)}>Duplizieren</button>}
              {draft.id !== null && !draft.builtin && (
                <button className="secondary small danger" onClick={() => void remove()}>{confirmDelete ? "Wirklich löschen?" : "Löschen"}</button>
              )}
            </div>
            {msg && <pre className={`editor-msg ${msg.ok ? "ok" : "fail"}`}>{msg.text}</pre>}
            <p className="muted small-note">Pine Script v5/v6 via PineTS (läuft isoliert im Browser-Worker, ohne Netzwerkzugriff). Nicht alle TradingView-Funktionen werden unterstützt (z. B. Tabellen, Labels).</p>
          </div>
        </div>
      </div>
    </div>
  );
}
