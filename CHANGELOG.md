# Changelog

## 2026-11-08 — Planning session
### Decisions
- Platform: self-hosted web app (Docker Compose) instead of Electron
- Database: PostgreSQL + TimescaleDB (relational cross-references + time series)
- Data: free sources first, optional paid provider (FMP/EODHD) later via adapter switch
- Target: Claude Code, single user (auth mandatory)
### Added
- `PROMPT.md`: build prompt incl. features (charting SMA/EMA/RSI/seasonality, scorecard, fair value, alerts, Claude chart analysis, Abilitato-style reports), data model, sources, security requirements, phases, Definition of Done
