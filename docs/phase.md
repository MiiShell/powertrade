# PowerTrade – Phasenplan & nächste Schritte

Stand: 2026-11-09 (Übergabe von Claude-Chat an Claude Code)

## Status
| Phase | Inhalt | Status |
|---|---|---|
| 0 | Grundgerüst, Auth, Docker, Test-/Prod-Deploy, CI | ✅ |
| 1 | Datenmodell, Provider (Yahoo/Stooq/Kraken/FMP), Import | ✅ |
| 2 | Charting: Candles, SMA/EMA/RSI, Divergenzen, S/R-Linien | ✅ |
| 3 | Saisonalität | ✅ |
| – | Detailseite: Technicals, Pivots, Profil, Kennzahlen | ✅ |
| – | Chart-Widgets, RSI optional, Pine Scripts + Editor | ✅ |
| 4 | Fundamentaldaten (SEC/FMP), 3 Qualitäts-Scores, Ranking, Aktienliste | 🔄 gebaut, **nicht deployt** |
| 5 | Fair Value (Standard + Pro) | ⏳ |
| 6 | Alerts | ⏳ |
| 7 | Claude-Chartanalyse | ⏳ |
| 8 | Claude-Berichte | ⏳ |
| 9 | Kreuzreferenzen | ⏳ |
| 10 | Hardening, Paid-Provider, VPS/Tailscale | ⏳ |

## Nächste Schritte (in dieser Reihenfolge)
1. **Phase 4 abschließen**
   - `./scripts/test-deploy.sh` → Fehler beheben (neu: Migration 0007, `test_stocks.py`).
   - `./scripts/deploy.sh` (fragt nach Bestätigung).
   - Live prüfen: Tab „Aktienliste“, NVDA-Scorecard; `fundamentals_run` muss `source=sec` zeigen
     (`docker compose -p powertrade exec db psql -U powertrade -c "select * from fundamentals_run"`).
   - Plausibilität NVDA: EPS-Reihe split-bereinigt stetig (keine Sprünge 2021/2024), Median-KGV realistisch (30–60).
2. **Phase 5 – Fair-Value-Engine** (Spezifikation: `docs/SCORING.md` §4/§5)
   - Tägliche Multiples (KGV/KCV/KUV/Div-Rendite) aus TTM bzw. letztem GJ, Median über 5/8/10/15/20 J.
   - FV-Linien (bil. Gewinn, Cashflow, Umsatz, Dividende), Bewertungslinien ±10 %-Schritte, Prognosekorridor
     (ohne Konsens: Trend-Extrapolation, markiert), „Rendite Fairer Wert“, Renditerechner.
   - Pro-Methoden: KBV-Historie, DCF (2 Stufen, Sensitivität), Graham, DDM, Blend nach Sektorprofil.
   - Discount-Kriterium der Scores auf die neue FV_std umstellen.
   - UI: FV-Chart wie Aktienfinder (Light/Pro), editierbare Ø-Multiples.
3. **Phase 6 – Alerts**: Regeln (Preis über/unter, %-Änderung, MA-Cross, RSI, FV-Upside), Telegram-Bot (Token als
   Docker-Secret), Dedup/Cooldown, Alert-Historie, Tab/Panel.

## Offene Punkte / technische Schulden
- Images auf Digests pinnen (timescaledb, redis, caddy, node, python, uv)
- CSP `'unsafe-inline'` → Nonces
- TOTP-Replay-Schutz
- Backups verschlüsseln + automatischer Restore-Test
- Krypto-Marktkapitalisierung/Profil (z. B. CoinGecko)
- Intraday-Timeframes
- `system_check.nonce`: `varchar` → `text`
- Pine: Tabellen/Labels/Lines/Boxes, `input()`-UI
- FMP-Fundamentaldaten: Split-Bereinigung klären (FMP evtl. bereits bereinigt)
- Weitere Stichproben der Technical Ratings gegen TradingView
- `_to_delete/` (Reste aus der Chat-Sitzung) löschen
