"""
Stock Discovery Engine.
Scans a broad universe (~300 tickers) for:
  - Next Compounder: high-growth, high-margin, early-stage
  - Sleeper Pick: profitable, moat, overlooked, reasonable valuation
Results are cached in memory for 24 hours. Scan runs in a background thread.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Broad universe (~300 tickers across all sectors and cap sizes)
# ---------------------------------------------------------------------------
DISCOVERY_UNIVERSE = list(dict.fromkeys([
    # Semiconductors
    "NVDA", "AMD", "AVGO", "QCOM", "TXN", "MU", "LRCX", "KLAC", "AMAT", "ON",
    "MRVL", "MPWR", "MCHP", "SWKS", "QRVO", "CRUS", "SLAB", "ALGM", "AMBA", "WOLF",
    "SITM", "SMCI", "ONTO", "COHU", "RMBS", "FORM", "ICHR", "KLIC", "POWI", "VICR",
    "ACLS", "IPGP", "MKSI", "DIOD", "AMKR",
    # AI / Data / Cloud infra
    "PLTR", "AI", "SOUN", "BBAI", "IONQ", "RXRX", "RKLB", "ASTS",
    # Software / SaaS / Cloud
    "CRM", "NOW", "ADBE", "WDAY", "TEAM", "MDB", "DDOG", "SNOW", "ZS", "CRWD",
    "NET", "PANW", "OKTA", "HUBS", "VEEV", "PAYC", "PCTY", "GTLB", "BILL", "NTNX",
    "PSTG", "PTC", "ANSS", "CDNS", "QLYS", "SPSC", "NCNO", "ALRM", "WK", "YEXT",
    "APPN", "BAND", "EGHT", "PRGS", "TTGT", "JAMF", "FIVN", "NICE",
    # Gaming / Consumer tech
    "TTWO", "U", "RBLX", "DUOL", "PINS", "SNAP", "SPOT", "ROKU",
    # Cybersecurity
    "FTNT", "CYBR", "S", "TENB", "VRNS", "SAIC", "LDOS", "BAH",
    # Health tech / Medtech
    "ISRG", "DXCM", "PODD", "ALGN", "IDXX", "MASI", "MMSI", "IRTC",
    "INSP", "NTRA", "EXAS", "GKOS", "SILK", "SWAV", "TMDX", "PRCT",
    "NARI", "OFIX", "USPH", "HALO", "LMAT", "RGEN",
    # Biotech
    "ACAD", "BEAM", "CRSP", "NTLA", "NVCR", "PTCT", "TGTX", "CPRX",
    # Consumer / Brands
    "LULU", "MNST", "CELH", "YETI", "WRBY", "XPEL", "SHAK", "SMPL",
    "TRIP", "HNST",
    # Defense / Aerospace / Gov tech
    "LMT", "RTX", "GD", "NOC", "KTOS", "AVAV", "HEI", "TDG", "AXON",
    "CACI", "JOBY", "ACHR",
    # Industrials
    "ESAB", "GTLS", "ITRI", "AAON", "APOG", "BLDR", "STRL", "MYRG",
    "DRVN", "ENSG", "GNTX", "JJSF", "PATK", "WERN", "TNET",
    # Clean energy
    "FSLR", "ENPH", "ARRY", "SHLS", "NOVA", "CWEN",
    # Fintech / Financial
    "SQ", "AFRM", "UPST", "SOFI", "NU", "FOUR", "GPN", "KNSL",
    "SIGI", "FCFS", "STEP", "COIN", "HOOD",
    # Telecom / Infrastructure
    "CIEN", "LITE", "COHR", "VIAV", "ARLO",
    # Small / Mid cap overlooked
    "NTST", "SANM", "SFNC", "VRRM", "WAFD", "WINA", "WLDN", "IBOC",
    "HCSG", "MGPI", "IOSP",
    # Large caps (for sleeper if temporarily out of favor)
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "INTC",
    "JPM", "BAC", "GS", "V", "MA", "PYPL",
    "XOM", "CVX", "COP", "OXY",
    "COST", "WMT", "TGT", "HD", "NKE", "SBUX",
    "DIS", "NFLX", "CMCSA",
    "JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY", "DHR", "TMO",
    "BA", "CAT", "DE", "HON", "GE", "ETN",
    "BMNR", "SCHD", "QQQM", "MSFT", "NVDA",
]))

# ---------------------------------------------------------------------------
# Scan state (in-memory cache)
# ---------------------------------------------------------------------------
_state: dict = {
    "status": "idle",       # idle | scanning | ready | error
    "progress": 0.0,
    "results": None,
    "generated_at": None,
    "error": None,
}
_lock = threading.Lock()

# Simple rate limiter for Finnhub (60 calls/min free tier)
_rate_lock = threading.Lock()
_last_call_ts: float = 0.0
_MIN_CALL_GAP = 1.05   # seconds between calls → ~57/min (safe under 60)


def _rate_limited_call(fn, *args, **kwargs):
    """Call fn with a minimum gap between calls to respect Finnhub rate limits."""
    global _last_call_ts
    with _rate_lock:
        now = time.time()
        wait = _MIN_CALL_GAP - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.time()
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_fundamentals(ticker: str) -> Optional[dict]:
    """Fetch Finnhub basic_financials for one ticker. Returns None on failure."""
    try:
        from services.finnhub_client import get_basic_financials
        metrics = _rate_limited_call(get_basic_financials, ticker)
        if not metrics:
            return None
        mc = metrics.get("marketCapitalization")
        if not mc or mc <= 0:
            return None
        return {
            "ticker": ticker,
            "name": ticker,          # name filled in later for finalists
            "sector": "Unknown",
            "market_cap": mc,        # millions
            "revenue_growth": metrics.get("revenueGrowthTTMYoy"),
            "eps_growth": metrics.get("epsGrowthTTMYoy"),
            "gross_margin": metrics.get("grossMarginTTM"),
            "net_margin": metrics.get("netProfitMarginTTM"),
            "roe": metrics.get("roeTTM"),
            "pe": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
            "ps": metrics.get("psTTM"),
            "pb": metrics.get("pbAnnual"),
            "debt_equity": metrics.get("debtToEquityAnnual"),
            "current_ratio": metrics.get("currentRatioAnnual"),
            "week52_high": metrics.get("52WeekHigh"),
            "week52_low": metrics.get("52WeekLow"),
        }
    except Exception as e:
        logger.debug("fundamentals fetch failed for %s: %s", ticker, e)
        return None


def _enrich_with_profile(data: list[dict]) -> None:
    """Mutate each dict in-place with company name and sector from Finnhub profile."""
    tickers = [d["ticker"] for d in data]
    for d in data:
        try:
            from services.finnhub_client import get_company_profile
            profile = _rate_limited_call(get_company_profile, d["ticker"])
            if profile:
                d["name"] = profile.get("name", d["ticker"])
                d["sector"] = profile.get("finnhubIndustry", "Unknown")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_compounder(d: dict) -> float:
    score = 0.0
    rev_g = d.get("revenue_growth") or 0
    if rev_g > 0.5:   score += 30
    elif rev_g > 0.3: score += 24
    elif rev_g > 0.2: score += 18
    elif rev_g > 0.1: score += 10

    gm = d.get("gross_margin") or 0
    if gm > 0.7:   score += 25
    elif gm > 0.5: score += 20
    elif gm > 0.4: score += 15
    elif gm > 0.25: score += 8

    mc = d.get("market_cap") or 0
    if 0 < mc < 2_000:      score += 20
    elif mc < 10_000:        score += 16
    elif mc < 30_000:        score += 12
    elif mc < 100_000:       score += 6

    eps_g = d.get("eps_growth") or 0
    if eps_g > 0.5:   score += 15
    elif eps_g > 0.25: score += 10
    elif eps_g > 0.1:  score += 6

    ps = d.get("ps") or 0
    if 0 < ps < 5:    score += 10
    elif ps < 15:     score += 7
    elif ps < 30:     score += 4
    elif ps > 0:      score += 1

    return score


def _score_sleeper(d: dict) -> float:
    score = 0.0
    pe = d.get("pe") or 0
    if pe <= 0:        score -= 20
    elif pe < 15:      score += 25
    elif pe < 22:      score += 18
    elif pe < 30:      score += 10

    rev_g = d.get("revenue_growth") or 0
    if rev_g > 0.15:   score += 20
    elif rev_g > 0.08: score += 14
    elif rev_g > 0.04: score += 8

    roe = d.get("roe") or 0
    if roe > 0.25:     score += 20
    elif roe > 0.18:   score += 15
    elif roe > 0.12:   score += 10
    elif roe > 0.08:   score += 5

    gm = d.get("gross_margin") or 0
    if gm > 0.5:       score += 15
    elif gm > 0.35:    score += 11
    elif gm > 0.20:    score += 6

    mc = d.get("market_cap") or 0
    if 500 < mc < 5_000:     score += 10
    elif 5_000 <= mc < 20_000: score += 7
    elif mc >= 20_000:       score += 4
    elif mc > 0:             score += 2

    cr = d.get("current_ratio") or 0
    if cr > 2.5:   score += 10
    elif cr > 1.5: score += 7
    elif cr > 1.0: score += 4

    return score


# ---------------------------------------------------------------------------
# Claude thesis
# ---------------------------------------------------------------------------

def _fmt_candidates(candidates: list[dict]) -> str:
    lines = []
    for d in candidates:
        mc_b = round((d.get("market_cap") or 0) / 1000, 1)
        rev_g = f"{round((d.get('revenue_growth') or 0)*100,1)}%"
        gm = f"{round((d.get('gross_margin') or 0)*100,1)}%"
        pe_str = f"PE={round(d['pe'],1)}" if (d.get("pe") or 0) > 0 else "PE=n/a"
        ps_str = f"PS={round(d['ps'],1)}" if d.get("ps") else ""
        roe_str = f"ROE={round((d.get('roe') or 0)*100,1)}%"
        lines.append(
            f"{d['ticker']} ({d['name']}) | {d['sector']} | ${mc_b}B mktcap | "
            f"RevGrowth={rev_g} | GrossMargin={gm} | {pe_str} {ps_str} | {roe_str}"
        )
    return "\n".join(lines)


def _claude_picks(candidates: list[dict], category: str) -> list[dict]:
    """Call Claude to select top 10 picks and write a thesis for each."""
    try:
        from services.claude_analyst import ClaudeAnalyst
        analyst = ClaudeAnalyst()

        data_str = _fmt_candidates(candidates)

        if category == "compounder":
            role = (
                "You are identifying the NEXT NVIDIA or PALANTIR — a high-growth company with "
                "explosive revenue growth, high gross margins (scalable model), and a dominant "
                "position in a massive expanding market. Profitability is NOT required. "
                "Focus on growth trajectory, market position, and long-term dominance potential."
            )
        else:
            role = (
                "You are identifying SLEEPER stocks — profitable, under-the-radar companies with "
                "strong moats that Wall Street hasn't fully discovered. Prioritize consistent "
                "profitability, high ROE, growing revenue, reasonable valuation, and durable "
                "competitive advantages: brand loyalty, switching costs, niche dominance, or "
                "network effects."
            )

        user = (
            f"CANDIDATES:\n{data_str}\n\n"
            f"{role}\n\n"
            "Select the TOP 10 picks. For each, write a specific 2-3 sentence thesis on WHY "
            "this company could be a life-changing investment. Be specific about the business "
            "model, competitive moat, and the growth catalyst.\n\n"
            "Return ONLY a JSON array with exactly this structure:\n"
            '[{"ticker":"XXXX","name":"Full Company Name",'
            '"thesis":"2-3 sentence thesis here",'
            '"key_metric":"Single most compelling number e.g. 67% revenue growth",'
            '"catalyst":"Specific trigger that could make this stock explode",'
            '"risk":"Main risk to this thesis"}]'
        )

        system = (
            "You are an elite hedge fund analyst identifying high-conviction long-term stock picks. "
            "Be specific, insightful, and data-driven. No generic platitudes. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )

        raw = analyst._call(system, user, max_tokens=3500)

        # Parse — response is a JSON array, not a dict
        import re as _re
        # Strip markdown fences if present
        clean = _re.sub(r'^```[a-z]*\n?', '', raw.strip(), flags=_re.MULTILINE)
        clean = _re.sub(r'\n?```$', '', clean.strip())
        clean = clean.strip()

        # Handle both array and {"picks": [...]} format
        parsed = json.loads(clean)
        if isinstance(parsed, list):
            return parsed[:10]
        if isinstance(parsed, dict):
            for key in ("picks", "tickers", "results", "data"):
                if isinstance(parsed.get(key), list):
                    return parsed[key][:10]
        return []
    except Exception as e:
        logger.error("Claude picks failed for %s: %s", category, e)
        return []


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def _run_scan() -> None:
    """Fetches fundamentals, scores, and calls Claude. Runs in a background thread."""
    with _lock:
        _state["status"] = "scanning"
        _state["progress"] = 0.0
        _state["error"] = None

    try:
        universe = DISCOVERY_UNIVERSE
        total = len(universe)
        logger.info("Discovery scan starting: %d tickers", total)

        # Phase 1: fetch fundamentals sequentially (rate-limited)
        fundamentals: list[dict] = []
        for i, ticker in enumerate(universe):
            result = _fetch_fundamentals(ticker)
            if result:
                fundamentals.append(result)
            with _lock:
                _state["progress"] = (i + 1) / total * 0.65
        logger.info("Discovery: fetched %d/%d fundamentals", len(fundamentals), total)

        # Phase 2: score
        compounder_pool = [
            d for d in fundamentals
            if (d.get("revenue_growth") or 0) > 0.05 and (d.get("gross_margin") or 0) > 0.2
        ]
        sleeper_pool = [
            d for d in fundamentals
            if (d.get("pe") or 0) > 2 and (d.get("pe") or 0) < 60
        ]

        top_compounders = sorted(compounder_pool, key=lambda d: -_score_compounder(d))[:35]
        top_sleepers = sorted(sleeper_pool, key=lambda d: -_score_sleeper(d))[:35]

        with _lock:
            _state["progress"] = 0.70

        # Phase 3: enrich top candidates with company names (rate-limited)
        all_finalists = {d["ticker"]: d for d in top_compounders + top_sleepers}
        unique_finalists = list(all_finalists.values())
        for i, d in enumerate(unique_finalists):
            try:
                from services.finnhub_client import get_company_profile
                profile = _rate_limited_call(get_company_profile, d["ticker"])
                if profile:
                    d["name"] = profile.get("name", d["ticker"])
                    d["sector"] = profile.get("finnhubIndustry", "Unknown")
            except Exception:
                pass
            with _lock:
                _state["progress"] = 0.70 + (i + 1) / len(unique_finalists) * 0.10

        with _lock:
            _state["progress"] = 0.80

        # Phase 4: Claude thesis
        compounder_picks = _claude_picks(top_compounders, "compounder")
        with _lock:
            _state["progress"] = 0.90

        sleeper_picks = _claude_picks(top_sleepers, "sleeper")
        with _lock:
            _state["progress"] = 0.95

        # Phase 5: enrich picks with metric data for frontend display
        fund_map = {d["ticker"]: d for d in fundamentals}

        def _enrich(picks: list[dict]) -> list[dict]:
            enriched = []
            for p in picks:
                t = p.get("ticker", "")
                d = fund_map.get(t, {})
                enriched.append({
                    "ticker": t,
                    "name": p.get("name") or d.get("name", t),
                    "sector": d.get("sector", ""),
                    "thesis": p.get("thesis", ""),
                    "key_metric": p.get("key_metric", ""),
                    "catalyst": p.get("catalyst", ""),
                    "risk": p.get("risk", ""),
                    "market_cap_b": round((d.get("market_cap") or 0) / 1000, 2),
                    "revenue_growth_pct": round((d.get("revenue_growth") or 0) * 100, 1),
                    "gross_margin_pct": round((d.get("gross_margin") or 0) * 100, 1),
                    "pe": round(d["pe"], 1) if (d.get("pe") or 0) > 0 else None,
                    "ps": round(d["ps"], 1) if d.get("ps") else None,
                    "roe_pct": round((d.get("roe") or 0) * 100, 1),
                })
            return enriched

        results = {
            "compounders": _enrich(compounder_picks),
            "sleepers": _enrich(sleeper_picks),
            "universe_size": total,
            "fundamentals_fetched": len(fundamentals),
        }

        with _lock:
            _state["status"] = "ready"
            _state["progress"] = 1.0
            _state["results"] = results
            _state["generated_at"] = datetime.now(tz=timezone.utc).isoformat()

        logger.info(
            "Discovery scan complete: %d compounders, %d sleepers",
            len(results["compounders"]), len(results["sleepers"]),
        )

    except Exception as e:
        logger.error("Discovery scan failed: %s", e, exc_info=True)
        with _lock:
            _state["status"] = "error"
            _state["error"] = str(e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_state() -> dict:
    with _lock:
        return dict(_state)


def trigger_scan(force: bool = False) -> bool:
    """
    Start a background scan. Returns True if scan was launched.
    If force=False and cache is < 24h old, returns False (use cache).
    """
    with _lock:
        if _state["status"] == "scanning":
            return False
        if not force and _state["status"] == "ready" and _state["results"]:
            gen = _state.get("generated_at")
            if gen:
                age_h = (
                    datetime.now(tz=timezone.utc) -
                    datetime.fromisoformat(gen)
                ).total_seconds() / 3600
                if age_h < 24:
                    return False

    t = threading.Thread(target=_run_scan, daemon=True)
    t.start()
    return True
