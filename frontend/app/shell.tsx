"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Chart } from "./chart";
import { Status } from "./status";
import { Stocks } from "./stocks";
import { Watchlist } from "./watchlist";

const TABS = [
  { id: "watchlist", label: "Watchlist" },
  { id: "stocks", label: "Aktienliste" },
  { id: "chart", label: "Chart" },
  { id: "reports", label: "Claude Reports" },
  { id: "status", label: "Status" },
] as const;
type TabId = (typeof TABS)[number]["id"];

type View = "chart" | "details";

function parseHash(): { tab: TabId; id: number | null; view: View } {
  const [h, rawId, rawView] = typeof window === "undefined" ? [] : window.location.hash.slice(1).split("/");
  const id = Number(rawId);
  return {
    tab: (TABS.find((t) => t.id === h)?.id ?? "watchlist") as TabId,
    id: Number.isInteger(id) && id > 0 ? id : null,
    view: rawView === "details" ? "details" : "chart",
  };
}

export function Shell({ user, onLogout }: { user: string; onLogout: () => Promise<void> }) {
  const [tab, setTab] = useState<TabId>("watchlist");
  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<View>("chart");

  useEffect(() => {
    const sync = () => {
      const h = parseHash();
      setTab(h.tab);
      setView(h.view);
      if (h.id !== null) setSelected(h.id);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const go = useCallback((id: TabId) => {
    window.location.hash = id; // back/forward + reload keep the tab
  }, []);

  const openChart = useCallback((s: { id: number }, v: View = "chart") => {
    window.location.hash = v === "details" ? `chart/${s.id}/details` : `chart/${s.id}`;
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">PowerTrade</span>
        <nav role="tablist" aria-label="Bereiche" className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              className={tab === t.id ? "tab active" : "tab"}
              onClick={() => go(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <span className="muted user">{user}</span>
        <button className="secondary small" onClick={async () => { await api.logout(); await onLogout(); }}>
          Abmelden
        </button>
      </header>

      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="content">
        {tab === "watchlist" && <Watchlist onOpenChart={openChart} />}
        {tab === "stocks" && <Stocks onOpen={(id) => openChart({ id }, "details")} />}
        {tab === "chart" && (
          <Chart
            instrumentId={selected}
            view={view}
            onSelect={(id) => openChart({ id }, view)}
            onView={(v) => (selected ? openChart({ id: selected }, v) : setView(v))}
          />
        )}
        {tab === "reports" && <ReportsPlaceholder />}
        {tab === "status" && <Status />}
      </section>
    </div>
  );
}

function ReportsPlaceholder() {
  return (
    <div className="panel">
      <h2>Claude Reports</h2>
      <p className="muted">Aktienberichte (Abilitato-Stil) und Chart-Analysen auf Abruf folgen in Phase 7/8.</p>
    </div>
  );
}
