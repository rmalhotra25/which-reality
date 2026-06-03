"""
CEF (Closed-End Fund) Scanner — scores popular CEFs by discount to NAV,
distribution rate, z-score, and leverage using CEFConnect public API.

Score (0-100):
  Discount to NAV : 35 pts  (deeper discount = better entry)
  Distribution    : 30 pts  (higher yield = more income)
  Z-Score 1-Year  : 20 pts  (more negative = unusually wide discount)
  Leverage        : 15 pts  (moderate leverage preferred 20-35%)

Cache TTL: 4 hours (/tmp/cache_cef_scan.json)
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_CACHE_FILE = "/tmp/cache_cef_scan.json"
_CACHE_TTL = 4 * 3600

_CEF_UNIVERSE = [
    # PIMCO income
    "PDI", "PTY", "PCI", "PHK", "RCS",
    # Multi-sector / corp bond
    "GOF", "AWF", "GHY", "EHI", "GLO", "RIV",
    # Senior loans / CLO
    "BGT", "EFT", "XFLT", "JRO",
    # Equity income
    "CII", "CSQ", "EXG", "ETJ", "BOE",
    # Preferred / hybrid
    "FPF", "JPS", "JPC", "HPI", "DFP",
    # Municipal
    "NVG", "NAD", "NEA", "NMZ", "BKN",
    # Infrastructure / utilities
    "UTF", "UTG",
    # Real estate
    "RNP", "NRO", "JRS",
    # MLP / energy
    "NTG", "CEM", "KYN",
    # Global income
    "FAX", "EDD",
]


def _fetch_cefconnect(ticker: str) -> dict | None:
    try:
        url = f"https://www.cefconnect.com/api/v3/pricingdata/{ticker}"
        resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            logger.debug("CEFConnect %s: HTTP %s", ticker, resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.debug("CEFConnect fetch failed for %s: %s", ticker, e)
        return None


def _calculate_score(
    pd_pct: float | None,
    dist_rate: float | None,
    z_score: float | None,
    leverage: float | None,
) -> int:
    score = 0

    # Discount to NAV (35 pts) — more negative PD = deeper discount = better entry
    if pd_pct is not None:
        if pd_pct <= -15:
            score += 35
        elif pd_pct <= -10:
            score += 28
        elif pd_pct <= -5:
            score += 20
        elif pd_pct < 0:
            score += 10
        # premium → 0 pts

    # Distribution rate (30 pts)
    if dist_rate is not None:
        if dist_rate >= 10:
            score += 30
        elif dist_rate >= 8:
            score += 24
        elif dist_rate >= 6:
            score += 18
        elif dist_rate >= 4:
            score += 12
        else:
            score += 6

    # Z-Score 1-year (20 pts) — negative = discount unusually wide vs history
    if z_score is not None:
        if z_score <= -2:
            score += 20
        elif z_score <= -1:
            score += 15
        elif z_score <= 0:
            score += 10
        elif z_score <= 1:
            score += 5
        # above +1 → 0 pts (premium signal)

    # Leverage (15 pts) — moderate leverage preferred, ultra-high = risky
    if leverage is not None:
        if 20 <= leverage <= 35:
            score += 15
        elif 10 <= leverage < 20 or 35 < leverage <= 45:
            score += 10
        elif leverage < 10:
            score += 7
        else:
            score += 4
    else:
        score += 8  # no leverage data → neutral

    return min(score, 100)


def analyze_cef(ticker: str) -> dict:
    """Fetch CEFConnect data and return a scored CEF result dict."""
    ticker = ticker.upper().strip()
    data = _fetch_cefconnect(ticker)
    if not data:
        raise ValueError(f"No CEFConnect data for {ticker}")

    pd_pct = data.get("PremiumDiscount")
    dist_rate = data.get("DistributionRate")
    z_score = data.get("ZScore1Year")
    leverage = data.get("Leverage")
    nav = data.get("NAV")
    price = data.get("MarketPrice")
    high_pd = data.get("52WeekHighPD")
    low_pd = data.get("52WeekLowPD")
    fund_name = data.get("FundName") or ticker

    score = _calculate_score(pd_pct, dist_rate, z_score, leverage)

    return {
        "ticker": ticker,
        "name": fund_name,
        "score": score,
        "nav": round(nav, 2) if nav is not None else None,
        "price": round(price, 2) if price is not None else None,
        "premium_discount_pct": round(pd_pct, 2) if pd_pct is not None else None,
        "distribution_rate_pct": round(dist_rate, 2) if dist_rate is not None else None,
        "z_score_1y": round(z_score, 2) if z_score is not None else None,
        "leverage_pct": round(leverage, 1) if leverage is not None else None,
        "pd_52w_high": round(high_pd, 2) if high_pd is not None else None,
        "pd_52w_low": round(low_pd, 2) if low_pd is not None else None,
    }


def _cache_read() -> dict | None:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("cached_at", 0) > _CACHE_TTL:
            return None
        return data
    except Exception:
        return None


def _cache_write(data: dict) -> None:
    try:
        data["cached_at"] = time.time()
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("CEF cache write failed: %s", e)


def scan_universe(force: bool = False) -> dict:
    """Scan all CEFs and return sorted results. Uses 4-hour file cache."""
    if not force:
        cached = _cache_read()
        if cached:
            logger.info("CEF scan: returning cached results")
            return cached

    results = []
    errors = []
    for ticker in _CEF_UNIVERSE:
        try:
            r = analyze_cef(ticker)
            results.append(r)
        except Exception as e:
            errors.append(ticker)
            logger.debug("CEF scan error for %s: %s", ticker, e)
        time.sleep(0.15)

    results.sort(key=lambda x: x["score"], reverse=True)

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "universe_count": len(_CEF_UNIVERSE),
        "scored_count": len(results),
        "top": results[:20],
        "all": results,
        "errors": errors,
    }
    _cache_write(output)
    logger.info("CEF scan complete: %d scored, %d errors", len(results), len(errors))
    return output
