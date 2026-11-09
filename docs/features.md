# PowerTrade – Feature-Übersicht

Stand: 2026-11-09 · Legende: ✅ live (deployt & geprüft) · 🔄 gebaut, Deploy/Check offen · ⏳ geplant

## Plattform & Sicherheit
| Feature | Status | Details |
|---|---|---|
| Self-hosted Docker-Stack | ✅ | Caddy, Next.js, FastAPI, ARQ-Worker, TimescaleDB, Redis; `https://localhost:8443` |
| Login | ✅ | 1 Admin, Argon2id + TOTP, Redis-Sessions (Logout widerruft), Throttling (5/15 min), CSRF-Origin-Check |
| Härtung | ✅ | Read-only-Container, `cap_drop: ALL`, internes Datennetz, Docker-Secrets, strikte CSP, Security-Header |
| Test-Deploy | ✅ | isolierter Stack, Zufalls-Secrets, Fixture-Daten, ~50 Smoke-Tests, Migrations-Roundtrip |
| Prod-Deploy | ✅ | Test-Gate → Build → Backup → Migration → Rollout → Caddy-Restart → Verify |
| CI | ✅ (Config) | ruff, mypy, pytest, Runtime-Import-Check, Frontend-Build, gitleaks, Trivy, Test-Deploy |

## Marktdaten
| Feature | Status | Details |
|---|---|---|
| Tageskerzen + Wochen-/Monats-Views | ✅ | `price_bar_1d` (Hypertable, Kompression ab 180 T), `price_bar_1w`, `price_bar_1mo` |
| Provider | ✅ | Yahoo (primär), Stooq, Kraken, FMP (Budget 240/Tag gepaced, 450 MB/30 T), Fallback nach Priorität |
| Import | ✅ | stündlich, 7-Tage-Overlap, idempotent, Protokoll `ingestion_run` |
| Watchlist | ✅ | hinzufügen/entfernen/aktualisieren, Startliste NVDA, BTC, ETH, SOL, XMR, Gold, Silber |
| Firmenprofil (FMP) | ✅ | bereinigt, wöchentlich, ergänzt ISIN/Börse/Land |
| Splits (Yahoo) | 🔄 | `corporate_action`, für Split-Bereinigung der Fundamentaldaten |

## Chart (Tab „Chart“)
| Feature | Status | Details |
|---|---|---|
| Candles, Volumen, 1T/1W, Zeiträume | ✅ | Lightweight Charts v5, de-DE-Formatierung |
| SMA/EMA (je bis 6 Perioden) | ✅ | Backend-berechnet mit Warm-up |
| RSI + Divergenzen (optional) | ✅ | Wilder-RSI, Pivot-Divergenzen (bull/bear) |
| S/R-Linien | ✅ | Klick zum Setzen, gespeichert, max. 50 |
| Widgets über dem Chart | ✅ | Kurs/Volumen, Tages-, Wochen-, 52-Wochen-Spanne, Fairer Wert (Aktien; Abstand, Bänder ±50 %, Klick → Details) |
| Pine Scripts | ✅ | PineTS im isolierten Worker; plot/hline/fill; Built-ins [Hoss] OBV RSI, [Hoss] VWAP Deviation |
| Pine-Editor | ✅ | neu/bearbeiten/testen/speichern/duplizieren/löschen |
| Pine-Tabellen/Labels/Boxen, `input()`-UI | ⏳ | offen |

## Detailseite (Chart → Details)
| Feature | Status | Details |
|---|---|---|
| Kopfkarte | ✅ | Kurs, Volumen vs. Ø30T, Spannen, Performance 1W–5Y, Allzeithoch |
| Technische Ratings | ✅ | 11 Oszillatoren + 15 MAs, 3 Tachos, 1T/1W/1M, TradingView-Regeln (BTC-Abgleich 25/26 → Ichimoku-Fix) |
| Pivots | ✅ | Classic, Fibonacci, Camarilla, Woodie, DM (gegen TradingView verifiziert) |
| Saisonalität | ✅ | Jahreslinien, Durchschnitt, Jahresbereich, Monats-Heatmap |
| Scorecard / Ranking / Fundamentaltabelle | ✅ | Phase 4 |

## Fundamentaldaten & Scores (Phase 4)
| Feature | Status | Details |
|---|---|---|
| SEC-EDGAR-Import | ✅ | 10–15+ Jahre US, Bereinigung, Restatements, Split-Bereinigung nach Einreichungsdatum |
| FMP-Fallback | ✅ | Statements + Dividenden (4 Calls/Aktie, budgetiert) |
| 3 Qualitäts-Scores (1–10) | ✅ | Dividendenertrag, Dividendenwachstum, Gewinnwachstum |
| Ranking 0–100 + Strategie-Editor | ✅ | Soll/Ist/Zielerreichung, Gewichte |
| Tab „Aktienliste“ | ✅ | sortierbar, Score-Badges, Ranking-Balken |

## Fair Value (Phase 5)
| Feature | Status | Details |
|---|---|---|
| FV-Linien | ✅ | Gewinn bereinigt (Standard), Cashflow, Umsatz, Dividende; Median täglicher Multiples 5/8/10/15/20 J./Alle |
| Bewertungslinien | ✅ | ±10 %-Schritte, grün unter-/rot überbewertet |
| Prognosekorridor | ✅ | 3 J., EPS-Trend (log-linear, max. ±20 % p.a.), markiert als Schätzung |
| Kennzahlen | ✅ | Abstand FV, Kauf-Limit (−20 %), Rendite Fairer Wert p.a., Jahrestabelle (KGV/KCV/KUV/Div., Δ-Werte) |
| Editierbare Ø-Multiples | ✅ | je Aktie gespeichert, wirken auf den Discount im Score |
| Renditerechner | ✅ | Betrag → Aktien, Kursgewinn, Dividende, Rendite p.a. |
| Aktienliste | ✅ | neue Spalten „Abstand FV“, „Rendite FV p.a.“ |
| Pro-Methoden (KBV, DCF, Graham, DDM, Blend) | ⏳ | Phase 5b |

## Geplant
| Feature | Phase |
|---|---|
| Fair Value Pro-Methoden (KBV-Historie, DCF, Graham, DDM, Blend nach Sektor) | 5b |
| Alerts (Preis, MA-Cross, RSI, Fair Value) via Telegram/E-Mail/Push | 6 |
| Claude-Chartanalyse auf Anfrage | 7 |
| Claude-Berichte (Abilitato-Stil), PDF, Kostenbremse | 8 |
| Kreuzreferenzen: ETF-Overlap, Sektor-Exposure, Korrelation, Beziehungsgraph | 9 |
| Hardening, Paid-Provider-Switch, VPS via Tailscale | 10 |

## API (alle unter `/api`, außer Health authentifiziert)
`health`, `health/ready` · `auth/login|logout|me` · `system/selfcheck` · `watchlist`, `watchlist/items[/{id}]` ·
`instruments/{id}/refresh|bars|chart|levels[/{lid}]|details|seasonality|stats|scorecard|profile/refresh|fundamentals/refresh` ·
`ingestion/runs` · `providers/usage` · `pine/scripts[/{id}]` · `stocks` · `ranking/strategy`
