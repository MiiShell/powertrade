# Feature Reference — extracted from Aktienfinder screenshots & table export (2026-11-08)

> Reference only. PowerTrade implements its own formulas (see `docs/SCORING.md`). Items marked *(inferred)* are deduced from raw data, not labelled in the source.

## 1. Stock Detail — Tabs
Unternehmensprofil · Scorecard · Qualitätscheck · Performance · Dividenden · Multiples · Fairer Wert ·
Gewinnfluss · Segmente · Regionen · Ranking · Benchmark · ETFs (count) · Analysen (count)

## 2. Scorecard
### Header panel
Logo, country flag, Branche, Sektor, Mitarbeiter, ISIN, Börsenwert, Aktienkurs, Kursgewinn 1J / 5J / 10J, Analysedatum.

### Three strategy profiles → each a **Qualitäts-Score 1–10**
Each criterion is a 10-segment bar on a fixed scale (left = worst, right = best).

| Criterion | Dividendenertrag | Dividendenwachstum | Gewinnwachstum |
|---|---|---|---|
| Gewinnstabilität | 0 → 1.0 | 0 → 1.0 | 0 → 1.0 |
| Gewinnwachstum (10J) | 0 % → 5 % | 0 % → 15 % | 0 % → 20 % |
| Max. Tilgungsjahre | ∞ → 2 | ∞ → 2 | ∞ → 2 |
| Momentum | −15 % → +15 % | −15 % → +15 % | −15 % → +15 % |
| Discount | 1 → 10 | 1 → 10 | 1 → 10 |
| Dividendenrendite | 0 % → 5 % | 0 % → 2 % | – (disabled) |
| Dividendenstabilität | 0 → 1.0 | 0 → 1.0 | – |
| Dividendenwachstum (10J) | 0 % → 5 % | 0 % → 15 % | – |

- Warning icon (!) next to a criterion when value is critical (e.g. Dividendenrendite).
- Example Home Depot: 6 / 8 / 6.
- In lists the three scores are shown as compact badges `[Ertrag|Wachstum|Gewinn]`, "-" if not applicable.

## 3. Ranking (user strategy)
- "Punkte: X von 100"
- Criteria: Stabilität des Gewinns, Zuwachs Gewinn 5 Jahre, Dividendenrendite, Zuwachs Dividende 5 Jahre,
  Stabilität der Dividende, Max. Tilgung Jahre, Min. Discount
- Per criterion: **Soll-Wert** (user target) vs **Ist-Wert** (bars, log scale right axis) + **Zielerreichung %** (line, capped at 100 %)
- Total = aggregated goal achievement → user-defined investment strategy

## 4. Fairer Wert (valuation chart)
- Mode toggle **Light / Pro**, save layout
- Series (toggleable): Kurs, Gewinn, Bereinigter Gewinn, Operativer CashFlow, Umsatz, Dividende,
  Fair Value bil. Gewinn, **Fair Value bereinigt**, Fair Value Cash-Flow, Fair Value Umsatz, Fair Value Dividende,
  Kursziel (analysts), **FV Prognosekorridor** (low/mid/high, ~3y forecast), **Bewertungslinien**
- Bewertungslinien: parallel bands around FV — green below (undervalued), red above (overvalued), ~5 each side *(inferred: fixed % steps)*
- Log toggle; range 5J / 8J / 10J / 15J / 20J / Alle; range navigator; grey "Prognose" zone
- Principle: **FV(t) = Ø multiple (chosen period) × metric per share(t)** — e.g. FV bereinigt = Ø KGV ber. × bereinigter EPS
- Yearly table under chart: KGV bil., KGV ber., KCV, KUV, Ø Div.; Δ Gewinn, Δ Gew. ber., Δ C-Flow, Δ Umsatz, Δ Div.
- Side panel "Bewertung": Zeitraum (e.g. 5 Jahre); Multiples **Schnitt (editable)** vs **Akt.**: KGV bil., KGV ber., KCV, KUV, Ø Div.
- Side panel "Aktienkauf" (return calculator): Betrag, Aktien → Kursgewinn, Dividende, Gesamt, Rendite, Rendite p.a., Pers. Dividende

## 5. Qualitätscheck (4 long-term charts, ~1991 → forecast)
1. **Gewinne, CashFlows und Dividenden** (per share): Gewinn, Bereinigter Gewinn, Freier CF, Operativer CF, Dividende, Pay-Out-Ratio (EPS/FFO %)
2. **Umsatz und Margen**: Umsatz, Brutto-, Operative-, Netto-Marge
3. **Verschuldung am Gesamtvermögen und Tilgungskraft**: Zinsfreie Schulden, Verzinste Schulden, Treasury Stocks, Goodwill,
   Cash+Wertpapiere, Kernvermögen, Tilgungskraft, Schuldenquote gesamt, Schuldenquote verzinst
4. **Aktienrückkäufe und Auswirkung auf den Gewinn**: EPS growth from buybacks vs organic, ausstehende Aktien
- "Chartlayout ändern", save, zoom per chart

## 6. ETFs tab (stock → ETFs containing it)
- ETF-Merkzettel (named lists), search, page size, pagination
- Columns: ETF (name, ISIN, logo), Merkzettel, Qualitäts-Scores (3), Land/Region, Fondsgröße, Index,
  **Qualitätsdichte %**, **Verklumpung %** (overlap/concentration), **Gewichtung im ETF**

## 7. Stock list / Watchlist
Columns: Aktie (logo, name, ISIN, ticker), Qualitäts-Scores (3), Merkzettel (checkbox), Sparplan (broker availability icons),
Kurs, **Kauf Limit** (editable, user value), Land, Branche, Marktkapitalisierung, Dividendenrendite,
Jährl. Zuwachs Dividende 5J (+ trend arrow), Kursgewinn 5J, Stabilität Gewinn (shield badge if high),
Dividenden nicht gesenkt seit Jahren (trophy badge). Sortable columns.

### Extended columns from table export (`attachment.txt`)
Identified per row, in order *(partly inferred)*:
1. Name, ISIN, Ticker
2. Ranking points (0–100) + 3 Qualitäts-Scores
3. Broker availability (consors, comdirect, ingtrading, traderepublic, scalable, finanzen, smartbroker)
4. Kurs, Kauf Limit
5. Region (Nordamerika, Europa (EUR), Europa (ex EUR), Asien, Australien), Sektor, Branche, Marktkapitalisierung
6. Dividend frequency (1/2/4) *(inferred)*, Dividende/Aktie, Dividendenrendite
7. Payout ratio on EPS %, payout ratio on FCF % *(inferred)*
8. Dividende nicht gesenkt seit (J), Dividende gezahlt seit (J) *(inferred)*
9. Growth blocks — CAGR values + stability (R², −1…1) for Dividende, Gewinn, bereinigter Gewinn, CashFlow, Umsatz *(inferred)*
10. Multiples: KGV, KGV bereinigt, KCV, KUV
11. Fairer Wert (EUR), **Rendite Fairer Wert** %, FV deviation per method: Bereinigt, Gewinn, CashFlow, Umsatz, Dividende
12. Schuldenquote %, Tilgung Jahre
13. Jährl. Kurszuwachs 10J, 5J
14. Kursgewinn 1T, 1W, 1M, 3M, 6M, YTD, 1J, 5J, 10J, 15J, 20J
15. Abstand zur 200-Tage-Linie %

## 8. Data requirements implied
- 20–35 years of annual fundamentals (EPS, adjusted EPS, CFO, FCF, revenue, margins, dividends, shares outstanding, debt split, goodwill, treasury stock)
- Analyst consensus (EPS/revenue forecasts 3y, price targets) → needed for Prognosekorridor
- ETF holdings with weights (→ Verklumpung / Qualitätsdichte)
- Broker savings-plan availability (manual table or scraping — low priority)
- ⚠️ Free sources cover this only partly → Phase 2 paid provider required for parity
