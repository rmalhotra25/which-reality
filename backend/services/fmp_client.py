"""
Financial Modeling Prep (FMP) client - used by the 12 Step screener.
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


def _get(path: str, params: dict | None = None, timeout: int = 15):
    key = settings.fmp_api_key
    if not key:
        return None
    q = dict(params or {})
    q["apikey"] = key
    url = f"{_FMP_BASE}{path}?{urlencode(q)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TradeIQ/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


_AIRLINE_KEYWORDS = ("airline", "airlines", "air transportation")
_COMMODITY_KEYWORDS = (
    "oil", "gas", "mining", "metals", "gold", "silver", "copper",
    "coal", "commodity", "steel", "aluminum",
)


def _is_excluded_industry(sector: str, industry: str, exclude_airlines: bool,
                           exclude_commodities: bool) -> bool:
    text = f"{sector or ''} {industry or ''}".lower()
    if exclude_airlines and any(k in text for k in _AIRLINE_KEYWORDS):
        return True
    if exclude_commodities and any(k in text for k in _COMMODITY_KEYWORDS):
        return True
    return False


def run_screener(
    market_cap_min: int = 1_000_000_000,
    market_cap_max: int | None = None,
    sector: str | None = None,
    min_volume: int = 200_000,
    country: str = "US",
    limit: int = 100,
    fcf_positive: bool = True,
    net_cash_positive: bool = True,
    revenue_growth_min: float = 10.0,
    short_interest_max: float = 10.0,
    operating_margin_min: float = 20.0,
    exclude_china: bool = True,
    exclude_airlines: bool = True,
    exclude_commodities: bool = True,
) -> dict:
    """Nash Step 3 screener.

    Returns a dict with status, results, and filters_omitted. Some Nash
    filters cannot be supplied by the free FMP screener data: short interest
    is not returned by the screener or ratios endpoints, net cash needs a
    balance sheet the screener does not return, and earnings surprise history
    is not returned, so those three are omitted and named, never faked.
    China exclusion is applied only through the country filter, because the
    screener response carries no separate domicile field. FCF positive is
    proxied by a positive FCF margin from the ratios endpoint.
    """
    if not settings.fmp_api_key:
        return {"status": "no_key", "results": [], "filters_omitted": ["all"]}

    filters_omitted = ["short_interest", "net_cash", "earnings_misses"]
    # Named here so the omission is explicit: neither value is applied
    # below, because the FMP screener data does not supply them.
    _ = (net_cash_positive, short_interest_max)
    if exclude_china:
        # Country filter is the only domicile signal available here.
        pass

    cache_key = (
        f"{market_cap_min}_{market_cap_max}_{sector}_{min_volume}_{country}_"
        f"{limit}_{fcf_positive}_{net_cash_positive}_{revenue_growth_min}_"
        f"{operating_margin_min}_{exclude_airlines}_{exclude_commodities}"
    )
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
        payload = {"status": "ok", "results": [], "filters_omitted": filters_omitted}
        _SCREENER_CACHE[cache_key] = (time.time(), payload)
        return payload

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
        sector = c.get("sector") or ""
        industry = c.get("industry") or ""
        if _is_excluded_industry(sector, industry, exclude_airlines, exclude_commodities):
            continue
        rev_growth = enr.get("revenue_growth")
        op_margin = enr.get("operating_margin")
        fcf_margin = enr.get("fcf_margin")
        # FMP ratios return decimals, so 0.10 means 10 percent.
        if rev_growth is not None and rev_growth < revenue_growth_min / 100.0:
            continue
        if op_margin is not None and op_margin < operating_margin_min / 100.0:
            continue
        if fcf_positive and fcf_margin is not None and fcf_margin <= 0:
            continue
        rule_of_40 = None
        if rev_growth is not None and fcf_margin is not None:
            rule_of_40 = (rev_growth + fcf_margin) * 100.0
        result.append({
            "ticker": sym,
            "name": c.get("companyName") or sym,
            "sector": sector,
            "industry": industry,
            "price": c.get("price"),
            "market_cap": c.get("marketCap"),
            "volume": c.get("volume"),
            "pe": enr.get("pe") or c.get("pe"),
            "gross_margin": enr.get("gross_margin"),
            "operating_margin": op_margin,
            "net_margin": enr.get("net_margin"),
            "fcf_margin": fcf_margin,
            "revenue_growth": rev_growth,
            "net_income_growth": enr.get("net_income_growth"),
            "fcf_growth": enr.get("fcf_growth"),
            "debt_to_equity": enr.get("debt_to_equity"),
            "rule_of_40": rule_of_40,
            "short_interest": None,
        })

    # Top 100 by Rule of 40, with unranked rows last.
    result.sort(key=lambda r: r["rule_of_40"] if r["rule_of_40"] is not None else -1e9, reverse=True)
    result = result[:100]
    payload = {"status": "ok", "results": result, "filters_omitted": filters_omitted}
    _SCREENER_CACHE[cache_key] = (time.time(), payload)
    return payload
