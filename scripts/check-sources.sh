#!/usr/bin/env bash
# Live check of external market data sources from the running worker container (real egress path).
# Usage: ./scripts/check-sources.sh   (prod stack must be running)
source "$(dirname "$0")/lib.sh"
require docker
docker compose -p powertrade exec -T worker python - <<'PY'
import asyncio
from datetime import date, timedelta

from app.market.bars import sanitize
from app.market.factory import fmp_budget
from app.market.providers import ProviderError, build_providers
from app.redis_conn import create_arq_redis
from app.settings import get_settings

CHECKS = [("yahoo", "NVDA"), ("yahoo", "SAP.DE"), ("yahoo", "BTC-USD"), ("yahoo", "GC=F"),
          ("stooq", "nvda.us"), ("kraken", "XBTUSD"), ("fmp", "NVDA")]

async def main() -> int:
    s = get_settings()
    redis = create_arq_redis(s)
    budget = fmp_budget(redis, s)
    providers, client = build_providers("live", s.http_user_agent, s.fmp_api_key, budget)
    failed = 0
    start = date.today() - timedelta(days=14)
    for name, sym in CHECKS:
        try:
            bars = sanitize(await providers[name].daily(sym, start))
            last = bars[-1] if bars else None
            ok = bool(bars)
            print(f"{'OK  ' if ok else 'EMPTY'} {name:7} {sym:10} bars={len(bars):3} "
                  f"last={last.ts.date() if last else '-'} close={last.close if last else '-'}")
            failed += not ok
        except ProviderError as e:
            print(f"FAIL {name:7} {sym:10} {e}")
            failed += 1
    print("FMP usage:", await budget.usage())
    if client:
        await client.aclose()
    await redis.aclose()
    return failed

raise SystemExit(asyncio.run(main()))
PY
