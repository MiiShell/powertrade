"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, type AlertEvent, type AlertKind, type AlertRule, type WatchItem } from "./api";

type Field = { key: string; label: string; def: string; kind: "num" | "ma" };
const FIELDS: Record<AlertKind, Field[]> = {
  price_above: [{ key: "price", label: "Kurs", def: "", kind: "num" }],
  price_below: [{ key: "price", label: "Kurs", def: "", kind: "num" }],
  change_pct: [
    { key: "pct", label: "Änderung % (±)", def: "5", kind: "num" },
    { key: "days", label: "Tage", def: "1", kind: "num" },
  ],
  ma_cross_above: [
    { key: "ma", label: "MA", def: "sma", kind: "ma" },
    { key: "period", label: "Periode", def: "200", kind: "num" },
  ],
  ma_cross_below: [
    { key: "ma", label: "MA", def: "sma", kind: "ma" },
    { key: "period", label: "Periode", def: "200", kind: "num" },
  ],
  rsi_above: [
    { key: "level", label: "RSI-Level", def: "70", kind: "num" },
    { key: "period", label: "Periode", def: "14", kind: "num" },
  ],
  rsi_below: [
    { key: "level", label: "RSI-Level", def: "30", kind: "num" },
    { key: "period", label: "Periode", def: "14", kind: "num" },
  ],
  fv_upside_above: [{ key: "pct", label: "Abstand zum FV ≥ %", def: "20", kind: "num" }],
};
const DELIVERY: Record<AlertEvent["delivery"], string> = {
  sent: "Telegram ✓", failed: "Telegram ✗", skipped: "nur App", pending: "läuft…",
};
const TG_STATUS: Record<string, string> = {
  telegram: "Telegram verbunden", fixture: "Test-Modus (kein Versand)", unknown: "Status unbekannt (Worker läuft?)",
};
const dt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "–");
const num = (v: number | null, d = 2) => (v === null ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));

export function Alerts({ instrumentId }: { instrumentId: number | null }) {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const [telegram, setTelegram] = useState("unknown");
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [unread, setUnread] = useState(0);
  const [kind, setKind] = useState<AlertKind>("price_above");
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<number | null>(null);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let active = true;
    void api.watchlist().then((r) => active && setItems(r.data?.items ?? []));
    void api.alerts().then((r) => {
      if (!active || !r.data) return;
      setRules(r.data.alerts);
      setKinds(r.data.kinds);
      setTelegram(r.data.telegram);
    });
    void api.alertEvents(100).then((r) => {
      if (!active || !r.data) return;
      setEvents(r.data.events);
      setUnread(r.data.unread);
    });
    const t = setInterval(reload, 30000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [version, reload]);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const params: Record<string, number | string> = {};
    for (const fld of FIELDS[kind]) {
      const raw = String(f.get(fld.key) ?? "").trim().replace(",", ".");
      params[fld.key] = fld.kind === "ma" ? raw : Number(raw);
    }
    const r = await api.createAlert({
      instrument_id: Number(f.get("instrument")),
      kind,
      params,
      note: String(f.get("note") ?? ""),
      cooldown_minutes: Math.round(Number(String(f.get("cooldown")).replace(",", ".")) * 60),
      notify_telegram: f.get("telegram") === "on",
      is_active: true,
    });
    if (r.status === 201) {
      setMsg("Alert angelegt – wird sofort geprüft");
      reload();
    } else {
      const d = (r.data as unknown as { detail?: unknown } | null)?.detail;
      setMsg(`Fehler ${r.status}${typeof d === "string" ? `: ${d}` : ""}`);
    }
  }

  async function toggle(rule: AlertRule) {
    const r = await api.updateAlert(rule.id, {
      instrument_id: rule.instrument_id, kind: rule.kind, params: rule.params, note: rule.note,
      cooldown_minutes: rule.cooldown_minutes, notify_telegram: rule.notify_telegram, is_active: !rule.is_active,
    });
    setMsg(r.status === 200 ? null : `Fehler ${r.status}`);
    reload();
  }

  async function remove(id: number) {
    if (confirmDel !== id) {
      setConfirmDel(id);
      return;
    }
    setConfirmDel(null);
    await api.deleteAlert(id);
    reload();
  }

  const stocks = new Set(items.filter((i) => i.type === "stock").map((i) => i.id));
  return (
    <>
      <div className="panel">
        <div className="row wrap">
          <h2>Alerts</h2>
          <span className="row gap">
            <span className="muted">{TG_STATUS[telegram] ?? `Telegram aus: ${telegram}`}</span>
            <button className="secondary small" onClick={async () => setMsg(`Test: ${(await api.telegramTest()).data?.status ?? "Fehler"}`)}>
              Test-Nachricht
            </button>
          </span>
        </div>
        <form className="alert-form" onSubmit={create}>
          <label>Instrument
            <select name="instrument" defaultValue={instrumentId ?? undefined} key={`i${instrumentId}${items.length}`}>
              {items.map((i) => <option key={i.id} value={i.id}>{i.symbol} – {i.name}</option>)}
            </select>
          </label>
          <label>Bedingung
            <select value={kind} onChange={(e) => setKind(e.target.value as AlertKind)}>
              {(Object.keys(FIELDS) as AlertKind[]).map((k) => <option key={k} value={k}>{kinds[k] ?? k}</option>)}
            </select>
          </label>
          {FIELDS[kind].map((fld) => (
            <label key={`${kind}${fld.key}`}>{fld.label}
              {fld.kind === "ma" ? (
                <select name={fld.key} defaultValue={fld.def}><option value="sma">SMA</option><option value="ema">EMA</option></select>
              ) : (
                <input name={fld.key} inputMode="decimal" defaultValue={fld.def} required />
              )}
            </label>
          ))}
          <label>Cooldown (Std.)<input name="cooldown" inputMode="decimal" defaultValue="24" /></label>
          <label className="grow">Notiz<input name="note" maxLength={200} /></label>
          <label className="check"><input type="checkbox" name="telegram" defaultChecked /> Telegram</label>
          <button type="submit">Anlegen</button>
        </form>
        {kind === "fv_upside_above" && <p className="muted small-note">Nur für Aktien mit Fundamentaldaten (Abstand = fairer Wert bereinigt / Kurs − 1).</p>}
        {msg && <p className="muted">{msg}</p>}

        {rules === null ? <p className="muted">Lade…</p> : rules.length === 0 ? <p className="muted">Noch keine Alerts.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Symbol</th><th>Bedingung</th><th className="num">Wert</th><th>Erfüllt</th><th>Ausgelöst</th><th>Cooldown</th><th>Kanal</th><th>Aktiv</th><th /></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className={r.is_active ? "" : "muted"}>
                    <td><strong>{r.symbol}</strong></td>
                    <td>{r.description}{r.note && <span className="muted"> · {r.note}</span>}
                      {r.kind === "fv_upside_above" && !stocks.has(r.instrument_id) && <span className="fail"> (keine Aktie)</span>}</td>
                    <td className="num">{num(r.last_value)}</td>
                    <td>{r.last_state === null ? "–" : r.last_state ? <span className="ok">ja</span> : "nein"}</td>
                    <td>{dt(r.last_triggered_at)}</td>
                    <td>{num(r.cooldown_minutes / 60, 0)} h</td>
                    <td>{r.notify_telegram ? "Telegram" : "App"}</td>
                    <td><input type="checkbox" aria-label="aktiv" checked={r.is_active} onChange={() => void toggle(r)} /></td>
                    <td><button className="link danger" onClick={() => void remove(r.id)}>{confirmDel === r.id ? "Wirklich löschen?" : "Löschen"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small-note">Prüfung nach jedem stündlichen Kursimport (Tageskerze). Ein Alert löst beim Übergang „nicht erfüllt → erfüllt“ aus, danach frühestens nach dem Cooldown erneut. MA-Kreuzungen werden erst ab der zweiten Prüfung gemeldet.</p>
      </div>

      <div className="panel">
        <div className="row wrap">
          <h2>Historie {unread > 0 && <span className="badge-count">{unread} neu</span>}</h2>
          {unread > 0 && <button className="secondary small" onClick={async () => { await api.markAlertsRead(); reload(); }}>Alle als gelesen markieren</button>}
        </div>
        {events.length === 0 ? <p className="muted">Noch keine ausgelösten Alerts.</p> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Zeit</th><th>Symbol</th><th>Meldung</th><th>Zustellung</th></tr></thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className={e.read_at ? "" : "unread"}>
                    <td>{dt(e.triggered_at)}</td>
                    <td><strong>{e.symbol}</strong></td>
                    <td className="pre">{e.message}</td>
                    <td className={e.delivery === "failed" ? "fail" : e.delivery === "sent" ? "ok" : "muted"} title={e.delivery_error ?? undefined}>
                      {DELIVERY[e.delivery]}{e.delivery_error && <span className="muted small"> ({e.delivery_error})</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
