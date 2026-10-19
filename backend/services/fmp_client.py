"""
Financial Modeling Prep (FMP) client — used by the 12 Step screener.
Free tier: 250 calls/day. Results are cached for 1 hour.
"""
import concurrent.futures
import json
import logging
import time
import urllib.request
from urllib.parse import urlencode

from config import settings

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api/v3"
_SCREENER_CACHE: dict = {}
_CACHE_TTL = 3600


def _get(path: str, params: dict | None = None):
    key = settings.fmp_api_key
    if not key:
        return None
    q = dict(params or {})
    q["apikey"] = key
    url = f"{_FMP_BASE}{path}?{urlencode(q)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TradeIQ/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("FMP %s failed: %s", path, e)
        return None


def _enrich_ticker(sym: str) -> dict:
    result: dict = {"ticker": sym}
    ratios = _get(f"/ratios/{sym}", {"limit": 1})
    if ratios and isinstance(ratios, list):
        r = ratios[0]
        result.update({
            "gross_margin": r.get("grossProfitMargin"),
            "operating_margin": r.get("operatingProfitMargin"),
            "net_margin": r.get("netProfitMargin"),
            "fcf_margin": r.get("freeCashFlowMargin"),
            "pe": r.get("priceEarningsRatio"),
            "debt_to_equity": r.get("debtEquityRatio"),
            "current_ratio": r.get("currentRatio"),
        })
    growth = _get(f"/financial-growth/{sym}", {"limit": 1})
    if growth and isinstance(growth, list):
        g = growth[0]
        result.update({
            "revenue_growth": g.get("revenueGrowth"),
            "net_income_growth": g.get("netIncomeGrowth"),
            "fcf_growth": g.get("freeCashFlowGrowth"),
        })
    return result


def run_screener(
    market_cap_min: int = 1_000_000_000,
    market_cap_max: int | None = None,
    sector: str | None = None,
    min_volume: int = 200_000,
    country: str = "US",
    limit: int = 40,
) -> list[dict]:
    if not settings.fmp_api_key:
        return []

    cache_key = f"{market_cap_min}_{market_cap_max}_{sector}_{min_volume}_{country}_{limit}"
    cached = _SCREENER_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        logger.info("FMP screener: cache hit for %s", cache_key)
        return cached[1]

    params: dict = {
        "marketCapMoreThan": market_cap_min,
        "volumeMoreThan": min_volume,
        "country": country,
        "limit": limit,
        "isActivelyTrading": "true",
    }
    if market_cap_max:
        params["marketCapLessThan"] = market_cap_max
    if sector:
        params["sector"] = sector

    candidates = _get("/stock-screener", params)
    if not candidates or not isinstance(candidates, list):
        return []

    top = candidates[:limit]
    tickers = [c.get("symbol") for c in top if c.get("symbol")]

    enriched_map: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_enrich_ticker, sym): sym for sym in tickers}
        for fut in concurrent.futures.as_completed(futures):
            sym = futures[fut]
            try:
                enriched_map[sym] = fut.result()
            except Exception as e:
                logger.debug("Enrichment failed for %s: %s", sym, e)

    result = []
    for c in top:
        sym = c.get("symbol")
        if not sym:
            continue
        enr = enriched_map.get(sym, {})
        result.append({
            "ticker": sym,
            "name": c.get("companyName") or sym,
            "sector": c.get("sector") or "",
            "industry": c.get("industry") or "",
            "price": c.get("price"),
            "market_cap": c.get("marketCap"),
            "volume": c.get("volume"),
            "pe": enr.get("pe") or c.get("pe"),
            "gross_margin": enr.get("gross_margin"),
            "operating_margin": enr.get("operating_margin"),
            "net_margin": enr.get("net_margin"),
            "fcf_margin": enr.get("fcf_margin"),
            "revenue_growth": enr.get("revenue_growth"),
            "net_income_growth": enr.get("net_income_growth"),
            "fcf_growth": enr.get("fcf_growth"),
            "debt_to_equity": enr.get("debt_to_equity"),
        })

    _SCREENER_CACHE[cache_key] = (time.time(), result)
    return result
