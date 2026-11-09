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
| 4 | Fundamentaldaten (SEC/FMP), 3 Qualitäts-Scores, Ranking, Aktienliste | ✅ deployt 2026-11-09 (Browser-Check offen) |
| 5 | Fair Value Standard | ✅ deployt 2026-11-09 (Browser-Check offen) |
| 5b | Fair Value Pro-Methoden | ⏳ |
| 6 | Alerts (Telegram + In-App) | ✅ deployt 2026-11-09 (Telegram-Secrets + Browser-Check offen) |
| 6b | Alerts per E-Mail / Web-Push | ⏳ |
| 7 | Claude-Chartanalyse | ⏳ |
| 8 | Claude-Berichte | ⏳ |
| 9 | Kreuzreferenzen | ⏳ |
| 10 | Hardening, Paid-Provider, VPS/Tailscale | ⏳ |

## Nächste Schritte (in dieser Reihenfolge)
1. **Browser-Check (manuell)**: Tab „Aktienliste“ (neue Spalten), NVDA-Details → Panel „Fairer Wert“ (Chart,
   Zeitraum-Umschalter, Ø-Multiples speichern/zurücksetzen, Renditerechner) und Scorecard.
   Live-Werte NVDA 2026-11-09: FV bereinigt 243 $ (Ø KGV 49,7, 10 J.), Kurs 186,64 $, Gewinnwachstum 10 J.
   56,8 % (log-linear), Scores 6/6/7, Ranking 76.
2. **Phase 5b – Pro-Methoden** (`docs/SCORING.md` §5): KBV-Historie (braucht BVPS = equity / shares), DCF 2-stufig
   mit Sensitivität, Graham, DDM, Blend nach Sektorprofil, Toggle „Pro“ im FV-Panel, Kauf-Limit wahlweise Pro.
3. **Telegram einrichten (manuell)**: Bot bei @BotFather anlegen, Chat-ID ermitteln, dann
   `./scripts/set-secret.sh telegram_bot_token`, `./scripts/set-secret.sh telegram_chat_id`, `./scripts/deploy.sh`,
   im Tab „Alerts“ → „Test-Nachricht“. Browser-Check: Alert anlegen/deaktivieren/löschen, Historie, Badge im Tab.
4. **Phase 7 – Claude-Chartanalyse** (PROMPT.md F5): Button „Mit Claude analysieren“, PNG + strukturiertes JSON,
   strukturierte Antwort (Trend, Levels, Momentum, Szenarien, Konfidenz), Kostenbremse, API-Key als Docker-Secret.

## Offene Punkte / technische Schulden
- Smoke-Tests: httpx `verify=<str>` deprecated → `ssl.create_default_context(cafile=...)`
- Alerts: Intraday-Auswertung erst mit Intraday-Daten sinnvoll; E-Mail/Web-Push (6b)
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
