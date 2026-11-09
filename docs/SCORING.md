# Scorecard, Ranking & Fair Value — Specification (v0.2)

Model: **Standard = Aktienfinder-style** (3 quality profiles, multiple-based fair value)
plus **Pro methods** (DCF, Graham, DDM, P/B) as optional add-ons.
UI reference: `docs/REFERENCE_AKTIENFINDER.md`. All parameters in `config/scoring.yaml` (versioned, editable in UI).
Every result stores `params_version`, `data_as_of`, `sources`, `confidence`.

## 0. Data Rules
- Annual (FY) data, split-adjusted, **diluted** shares, converted to trading currency (ECB FX at period end).
- Windows: growth/stability default 10y (stability up to 20y if available). < 5y → `confidence=low`; < 3y → criterion `N/A`.
- `N/A` criteria are excluded from averages (never counted as 0).
- Financials (banks, insurers): Tilgungsjahre, KCV-FV, DCF = `N/A`.
- Multiples: drop values outside (0, 100] (KGV/KCV) and (0, 30] (KUV) before averaging; use **median**.

## 1. Base Metrics

| Metric | Definition |
|---|---|
| **Stability(X)** | Signed R² of OLS fit `X_t ~ t` (linear, handles negatives): `sign(slope) × R²` → range −1…1 |
| **TrendGrowth(X, n)** | CAGR between fitted trendline start and end over n years: `(fit_end / fit_start)^(1/n) − 1`; `fit_start ≤ 0` → `N/A` (robust vs. outlier start/end years) |
| **Tilgungsjahre** | `net_interest_bearing_debt / mean(FCF, 3y)`; net debt ≤ 0 → 0 years; FCF ≤ 0 → ∞ |
| **Momentum** | `price / SMA200 − 1` (configurable: 6M/12M return) |
| **Discount** | Position in valuation bands (section 4): `clamp(5.5 − (price / FV_std − 1) / 0.10, 1, 10)` → 1 = strongly overvalued, 10 = strongly undervalued |
| **Dividendenrendite** | `DPS_ttm / price` |

EPS basis for stability/growth: **adjusted EPS** (fallback reported EPS). Dividends: DPS (REITs: FFO-based payout).

## 2. Quality Scores — 3 Profiles (1–10)
Each criterion → sub-score `s = clamp(10 × (v − min) / (max − min), 0, 10)` on its scale (inverted scales handled).
Tilgungsjahre uses `s = clamp(20 / years, 0, 10)` (2 years → 10, ∞ → 0).
**Profile score = clamp(round(mean(s of active criteria)), 1, 10)** (optional weights in config).

| Criterion | Dividendenertrag | Dividendenwachstum | Gewinnwachstum |
|---|---|---|---|
| Gewinnstabilität | 0 → 1.0 | 0 → 1.0 | 0 → 1.0 |
| Gewinnwachstum (10J) | 0 → 5 % | 0 → 15 % | 0 → 20 % |
| Max. Tilgungsjahre | ∞ → 2 | ∞ → 2 | ∞ → 2 |
| Momentum | −15 → +15 % | −15 → +15 % | −15 → +15 % |
| Discount | 1 → 10 | 1 → 10 | 1 → 10 |
| Dividendenrendite | 0 → 5 % | 0 → 2 % | – |
| Dividendenstabilität | 0 → 1.0 | 0 → 1.0 | – |
| Dividendenwachstum (10J) | 0 → 5 % | 0 → 15 % | – |

- Non-dividend payers: dividend profiles = `N/A` (shown as "-"), Gewinnwachstum profile still scored.
- Warning flag (!) when a sub-score ≤ 2.
- UI: 10-segment bar per criterion, raw value + formula in tooltip; list view shows badges `[E|W|G]`.

## 3. Ranking — User Strategy (0–100 points)
Criteria with user-defined **Soll** (targets stored per strategy, multiple strategies allowed):
Stabilität Gewinn, Zuwachs Gewinn 5J, Dividendenrendite, Zuwachs Dividende 5J, Stabilität Dividende, Max. Tilgungsjahre, Min. Discount.
- Higher-is-better: `Ziel_i = clamp(Ist / Soll, 0, 1)`; lower-is-better (Tilgungsjahre): `clamp(Soll / Ist, 0, 1)`
- Negative Ist → 0
- `Punkte = round(100 × Σ wᵢ·Zielᵢ / Σ wᵢ)` (default equal weights)
- Chart: Soll vs Ist bars (log axis) + Zielerreichung line

## 4. Fair Value — Standard (Aktienfinder-style)
Per-share metrics (TTM, daily-stepped): EPS reported, EPS adjusted, OCF/share, revenue/share, DPS.

| FV line | Formula |
|---|---|
| FV bil. Gewinn | `Ø KGV_bil × EPS` |
| **FV bereinigt (default)** | `Ø KGV_ber × EPS_adj` |
| FV Cash-Flow | `Ø KCV × OCF_ps` |
| FV Umsatz | `Ø KUV × Rev_ps` |
| FV Dividende | `DPS / Ø Div-Rendite` |

- **Ø multiple** = median of daily multiples over chosen period (5 / 8 / 10 / 15 / 20J / Alle, default 10J); user can override "Schnitt" (stored per stock).
- **FV_std** = FV bereinigt (used for Discount, Kauf-Limit suggestion, alerts).
- **Bewertungslinien**: `FV_std × (1 + k × 10 %)`, k = −5…+5 (green below, red above).
- **Prognosekorridor** (3y): `Ø KGV_ber × consensus EPS (low / mean / high)`. Without consensus data (Phase 1): trend extrapolation `EPS_adj × (1 + TrendGrowth)^t`, flagged `estimate=trend`.
- **Rendite Fairer Wert** (expected p.a. return): `(FV_corridor_mean(t+3) / price)^(1/3) − 1 + Div-Rendite`.
- Yearly table: KGV bil., KGV ber., KCV, KUV, Ø Div.; Δ Gewinn, Δ Gew. ber., Δ C-Flow, Δ Umsatz, Δ Div.
- **Aktienkauf calculator**: Betrag → Aktien; at FV target: Kursgewinn, Dividende, Gesamt, Rendite, Rendite p.a., persönliche Dividendenrendite.

## 5. Fair Value — Pro Methods (toggle "Pro")
`EPS_fwd` = consensus EPS next FY (fallback `EPS_ttm × (1 + min(TrendGrowth, 10 %))`).

| Method | Formula | Valid if |
|---|---|---|
| P/B history | `median(P/B, period) × BVPS` | BVPS > 0 |
| DCF 2-stage | see below | FCF₀ > 0, not financials |
| Graham | `sqrt(22.5 × EPS_ttm × BVPS)` | EPS, BVPS > 0 |
| DDM 2-stage | see below | dividend, payout ≤ 100 % |

**DCF**: `FCF₀` = mean FCF 3y; years 1–5 `g1 = clamp(FCF/EPS CAGR 5y, 0, 15 %)`, years 6–10 linear fade to `g_t = 2 %`;
`r = rf + β × ERP` (ERP 5.5 %, β ∈ [0.6, 2.0]; fallback 9 %); guard `r ≥ g_t + 3 %`;
`TV = FCF₁₀ × (1 + g_t) / (r − g_t)`; `FV = (Σ PV + PV(TV) − net_debt) / diluted_shares`. All inputs editable + sensitivity table (r ±1 %, g_t ±0.5 %).

**DDM**: `g1 = clamp(DGR 5y, 0, 8 %)` for 5y, then `g_t = 2.5 %`, same `r`.

**Pro blend** (renormalized over valid methods):

| Profile | FV bereinigt | P/B | DCF | Graham | DDM |
|---|---|---|---|---|---|
| default | 40 | 10 | 30 | 10 | 10 |
| financials | 40 | 40 | – | – | 20 |
| growth (no dividend) | 50 | – | 50 | – | – |
| REIT | 20 | 30 | 20 | – | 30 |

- Show range `[min, max]`; `max/min > 2.5` → `confidence=low`.
- Margin of safety (default 20 %) → suggested **Kauf-Limit** = `FV × (1 − MoS)` (Standard or Pro, user choice).

## 6. Scope
Stocks only. ETFs: aggregated scores = holdings-weighted average (Phase 9), plus Verklumpung/overlap. Crypto: charting + alerts only.

## 7. Tests (required)
- Unit tests per formula with hand-calculated fixtures (negative EPS, no dividend, financials, < 5y history, net cash).
- Golden tests: 3 tickers (dividend grower, growth stock, bank) with snapshot outputs.

## 8. Implementation notes (v0.2.1, Phase 4)
- EPS basis: diluted EPS from filings (adjusted EPS not available from free sources); per-share data split-adjusted.
- Gewinnwachstum: if the EPS trendline start/end is <= 0 the criterion scores **0 points** (penalised, not N/A).
- Discount uses an annual approximation of FV_std until Phase 5: median P/E over the last 10 fiscal years
  (FY-end close / EPS, 0 < P/E <= 100, min. 3 years) x latest EPS.
- Dividend yield = last fiscal-year DPS / current price.
- Financials (sector Financial Services/Financials/Banks/Insurance): payback years N/A.

## Changelog
- v0.2.1: implementation notes (EPS basis, negative growth = 0 points, annual FV_std approximation).
- v0.2: Aktienfinder-style standard model (3 profiles 1–10, ranking 0–100, multiple-based FV with bands & corridor); v0.1 methods moved to Pro.
- v0.1: single scorecard 0–15 + blended FV (superseded).
