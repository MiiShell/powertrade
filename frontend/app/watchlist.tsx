"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, type WatchItem } from "./api";

const TYPES = ["stock", "etf", "index", "crypto", "commodity", "fx"];

function fmt(n: number | null, digits = 2) {
  return n === null ? "–" : n.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function Watchlist({ onOpenChart }: { onOpenChart: (s: { id: number; symbol: string }, view?: "chart" | "details") => void }) {
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let active = true;
    void api.watchlist().then((r) => {
      if (active) setItems(r.data?.items ?? []);
    });
    const t = setInterval(reload, 15000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [version, reload]);

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setError(null);
    const r = await api.addItem(String(f.get("symbol")), String(f.get("type")), String(f.get("currency")));
    if (r.status === 201) {
      form.reset();
      reload();
    } else setError(`Hinzufügen fehlgeschlagen (${r.status})`);
  }

  return (
    <div className="panel">
      <h2>Watchlist</h2>
      {items === null ? (
        <p className="muted">Lade…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th><th>Name</th><th className="num">Kurs</th><th className="num">Änd. %</th>
              <th>Stand</th><th>Import</th><th />
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td><button className="link symbol" onClick={() => onOpenChart({ id: i.id, symbol: i.symbol })} title="Chart öffnen">{i.symbol}</button></td>
                <td className="muted">{i.name}</td>
                <td className="num">{fmt(i.last_close)} {i.currency}</td>
                <td className={`num ${(i.change_pct ?? 0) >= 0 ? "ok" : "fail"}`}>{fmt(i.change_pct)}</td>
                <td className="muted">{i.last_date ?? "–"}</td>
                <td className={i.ingestion.status === "success" ? "ok" : i.ingestion.status === "failed" ? "fail" : "muted"}
                    title={i.ingestion.error ?? ""}>
                  {i.ingestion.status ?? "–"}
                </td>
                <td className="actions">
                  <button className="secondary small" title="Details" onClick={() => onOpenChart({ id: i.id, symbol: i.symbol }, "details")}>ⓘ</button>
                  <button className="secondary small" onClick={async () => { await api.refresh(i.id); reload(); }}>↻</button>
                  <button className="secondary small" onClick={async () => { await api.removeItem(i.id); reload(); }}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="inline" onSubmit={add}>
        <input name="symbol" placeholder="Symbol (z. B. SAP.DE)" required pattern="[A-Za-z0-9.\-=^_]{1,32}" />
        <select name="type" defaultValue="stock">{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
        <input name="currency" defaultValue="USD" size={4} pattern="[A-Za-z]{3}" required />
        <button>Hinzufügen</button>
      </form>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
