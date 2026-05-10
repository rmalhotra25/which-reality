"""
Stock Discovery Engine — Multi-Factor Model v2.
Scans a broad universe (~300 tickers) for:
  - Next Compounder: high-growth, high-margin, accelerating revenue, price momentum
  - Sleeper Pick: profitable, moat, low valuation, high ROIC, overlooked

Scoring uses percentile-normalized multi-factor model so every metric is
judged relative to the scanned universe — not arbitrary fixed thresholds.

Results are cached in memory for 24 hours. Scan runs in a background thread.
"""
import json
import logging
import threading
import time
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

        # Revenue growth: try quarterly (acceleration signal) then TTM
        rev_growth_q = (
            metrics.get("revenueGrowth3M") or
            metrics.get("revenueGrowthQuarterlyYoy") or
            metrics.get("revenueGrowth1Q")
        )

        # FCF margin: try multiple field names Finnhub uses
        fcf_margin = (
            metrics.get("fcfMarginTTM") or
            metrics.get("freeCashFlowMarginTTM") or
            metrics.get("fcfMargin5Y")
        )

        # ROIC: try multiple field names
        roic = (
            metrics.get("roicTTM") or
            metrics.get("returnOnInvestedCapitalTTM") or
            metrics.get("roiTTM")
        )

        return {
            "ticker": ticker,
            "name": ticker,
            "sector": "Unknown",
            # Size
            "market_cap": mc,                                          # millions
            # Growth
            "revenue_growth": metrics.get("revenueGrowthTTMYoy"),     # TTM YoY
            "revenue_growth_q": rev_growth_q,                          # recent qtr YoY
            "eps_growth": metrics.get("epsGrowthTTMYoy"),
            "eps_growth_q": metrics.get("epsGrowthQuarterlyYoy"),
            # Margins / quality
            "gross_margin": metrics.get("grossMarginTTM"),
            "operating_margin": metrics.get("operatingMarginTTM"),
            "net_margin": metrics.get("netProfitMarginTTM"),
            "fcf_margin": fcf_margin,
            # Price momentum (from same API call — no extra request needed)
            "return_6m": metrics.get("26WeekPriceReturnDaily"),        # 6-month %
            "return_3m": metrics.get("13WeekPriceReturnDaily"),        # 3-month %
            "return_1y": metrics.get("52WeekPriceReturnDaily"),        # 1-year %
            "week52_high": metrics.get("52WeekHigh"),
            "week52_low": metrics.get("52WeekLow"),
            # Valuation
            "pe": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
            "ps": metrics.get("psTTM"),
            "pb": metrics.get("pbAnnual"),
            # Capital efficiency
            "roe": metrics.get("roeTTM"),
            "roa": metrics.get("roaTTM"),
            "roic": roic,
            # Financial health
            "debt_equity": metrics.get("debtToEquityAnnual"),
            "current_ratio": metrics.get("currentRatioAnnual"),
        }
    except Exception as e:
        logger.debug("fundamentals fetch failed for %s: %s", ticker, e)
        return None


def _add_derived_signals(fundamentals: list[dict]) -> None:
    """Compute derived signals in-place. Called after all fundamentals are fetched."""
    for d in fundamentals:
        # Revenue acceleration: recent quarter growth vs TTM growth
        # Positive = speeding up (early innings signal), negative = slowing
        rev_ttm = d.get("revenue_growth") or 0.0
        rev_q = d.get("revenue_growth_q")
        d["rev_accel"] = (rev_q - rev_ttm) if rev_q is not None else None

        # Growth efficiency: revenue growth per unit of valuation (PEG-style)
        # High growth at low PS = highly efficient. Neutral if PS unknown.
        ps = d.get("ps") or 0
        rev_g = d.get("revenue_growth") or 0
        d["growth_efficiency"] = rev_g / max(ps, 0.5) if ps > 0 and rev_g > 0 else None

        # Earnings yield (1/PE) — value signal for sleepers
        pe = d.get("pe") or 0
        d["earnings_yield"] = 1.0 / pe if 2 < pe < 200 else None


# ---------------------------------------------------------------------------
# Multi-factor scoring (percentile-normalized)
# ---------------------------------------------------------------------------

def _pct_ranks(pool: list[dict], field: str, ascending: bool = True) -> dict[str, float]:
    """
    Returns {ticker: rank} where rank is 0-100.
    ascending=True → higher field value = rank 100 (best).
    ascending=False → lower field value = rank 100 (best).
    Missing/None values get rank 50 (neutral — no penalty, no bonus).
    """
    pairs = [(d["ticker"], d.get(field)) for d in pool]
    valid = []
    for t, v in pairs:
        try:
            fv = float(v)
            if fv == fv:  # excludes NaN
                valid.append((t, fv))
        except (TypeError, ValueError):
            pass

    if len(valid) < 2:
        return {t: 50.0 for t, _ in pairs}

    sorted_vals = sorted(valid, key=lambda x: x[1])
    n = len(sorted_vals)
    if ascending:
        rank_map = {t: (i / (n - 1)) * 100 for i, (t, _) in enumerate(sorted_vals)}
    else:
        rank_map = {t: ((n - 1 - i) / (n - 1)) * 100 for i, (t, _) in enumerate(sorted_vals)}

    return {t: rank_map.get(t, 50.0) for t, _ in pairs}


def _build_compounder_scores(pool: list[dict]) -> dict[str, float]:
    """
    Multi-factor compounder score (weights sum to 1.0):
      Revenue Growth (TTM YoY)      20%  top-line velocity
      Revenue Acceleration          10%  recent quarter faster than TTM?
      Gross Margin                  15%  scalable / software-like model
      FCF Margin                    10%  real cash generation
      6-Month Price Momentum        15%  market is already recognizing this
      3-Month Price Momentum         5%  recent confirmation
      Growth Efficiency (RevG/PS)   10%  not overpaying for the growth
      ROIC                          10%  management deploys capital well
      EPS Growth                     5%  earnings catching up to revenue
    """
    r = {
        "rev_g":    _pct_ranks(pool, "revenue_growth"),
        "rev_acc":  _pct_ranks(pool, "rev_accel"),
        "gm":       _pct_ranks(pool, "gross_margin"),
        "fcf":      _pct_ranks(pool, "fcf_margin"),
        "mom6":     _pct_ranks(pool, "return_6m"),
        "mom3":     _pct_ranks(pool, "return_3m"),
        "eff":      _pct_ranks(pool, "growth_efficiency"),
        "roic":     _pct_ranks(pool, "roic"),
        "eps":      _pct_ranks(pool, "eps_growth"),
    }
    weights = {
        "rev_g": 0.20, "rev_acc": 0.10, "gm": 0.15, "fcf": 0.10,
        "mom6": 0.15, "mom3": 0.05, "eff": 0.10, "roic": 0.10, "eps": 0.05,
    }
    scores = {}
    for d in pool:
        t = d["ticker"]
        scores[t] = sum(r[k].get(t, 50.0) * w for k, w in weights.items())
    return scores


def _build_sleeper_scores(pool: list[dict]) -> dict[str, float]:
    """
    Multi-factor sleeper score (weights sum to 1.0):
      P/E (lower = better)          20%  value signal — not priced for perfection
      ROE                           20%  management efficiency / durable moat
      Revenue Growth                15%  not a dying business
      Gross Margin                  15%  durable profit engine
      FCF Margin                    10%  real earnings (not accounting games)
      ROIC                          10%  capital allocation quality
      Current Ratio                  5%  financial safety
      Debt/Equity (lower = better)   5%  balance sheet resilience
    """
    r = {
        "pe":   _pct_ranks(pool, "pe",           ascending=False),  # cheaper = better
        "roe":  _pct_ranks(pool, "roe"),
        "rev":  _pct_ranks(pool, "revenue_growth"),
        "gm":   _pct_ranks(pool, "gross_margin"),
        "fcf":  _pct_ranks(pool, "fcf_margin"),
        "roic": _pct_ranks(pool, "roic"),
        "cr":   _pct_ranks(pool, "current_ratio"),
        "de":   _pct_ranks(pool, "debt_equity",  ascending=False),  # lower debt = better
    }
    weights = {
        "pe": 0.20, "roe": 0.20, "rev": 0.15, "gm": 0.15,
        "fcf": 0.10, "roic": 0.10, "cr": 0.05, "de": 0.05,
    }
    scores = {}
    for d in pool:
        t = d["ticker"]
        scores[t] = sum(r[k].get(t, 50.0) * w for k, w in weights.items())
    return scores


# ---------------------------------------------------------------------------
# Claude thesis
# ---------------------------------------------------------------------------

def _fmt_candidates(candidates: list[dict]) -> str:
    lines = []
    for d in candidates:
        mc_b = round((d.get("market_cap") or 0) / 1000, 1)

        rev_g = d.get("revenue_growth") or 0
        rev_q = d.get("revenue_growth_q")
        accel_tag = ""
        if rev_q is not None:
            if rev_q > rev_g + 0.05:
                accel_tag = " [↑ACCEL]"
            elif rev_q < rev_g - 0.05:
                accel_tag = " [↓DECEL]"
        rev_str = f"{round(rev_g * 100, 1)}%{accel_tag}"

        gm_str   = f"GrossMargin={round((d.get('gross_margin') or 0)*100,1)}%"
        fcf_str  = f"FCFMargin={round((d.get('fcf_margin') or 0)*100,1)}%" if d.get("fcf_margin") is not None else ""
        mom_str  = f"6moReturn={round(d.get('return_6m') or 0,1)}%" if d.get("return_6m") is not None else ""
        pe_str   = f"PE={round(d.get('pe'),1)}" if (d.get("pe") or 0) > 0 else "PE=n/a"
        ps_str   = f"PS={round(d.get('ps'),1)}" if d.get("ps") else ""
        roe_str  = f"ROE={round((d.get('roe') or 0)*100,1)}%"
        roic_str = f"ROIC={round((d.get('roic') or 0)*100,1)}%" if d.get("roic") else ""

        # Insider signal
        insider_str = ""
        sig = d.get("insider_signal", "neutral")
        n_buy = d.get("insiders_buying", 0) or 0
        n_sell = d.get("insiders_selling", 0) or 0
        if sig == "buy" and n_buy >= 2:
            insider_str = f"InsiderBuying={n_buy}execs"
        elif sig == "sell" and n_sell >= 2:
            insider_str = f"InsiderSelling={n_sell}execs"

        # Short interest (high DTC = potential squeeze fuel for sleepers)
        short_str = ""
        dtc = d.get("days_to_cover")
        if dtc and dtc > 5:
            short_str = f"ShortDTC={dtc}d"

        parts = [
            f"{d['ticker']} ({d['name']}) | {d['sector']} | ${mc_b}B",
            f"RevGrowth={rev_str}",
            gm_str,
        ]
        for extra in (fcf_str, mom_str, pe_str, ps_str, roe_str, roic_str,
                      insider_str, short_str):
            if extra:
                parts.append(extra)

        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _claude_picks(candidates: list[dict], category: str) -> list[dict]:
    """Call Claude to select top 10 picks and write a thesis for each."""
    try:
        from services.claude_analyst import ClaudeAnalyst
        analyst = ClaudeAnalyst()

        data_str = _fmt_candidates(candidates)

        if category == "compounder":
            role = (
                "You are identifying the NEXT NVIDIA or PALANTIR — a company with explosive "
                "revenue growth, high gross margins (scalable model), and dominant position in "
                "a massive expanding market. Key signals: revenue ACCELERATION (recent quarter "
                "faster than TTM, marked [↑ACCEL]), strong price momentum (already moving), "
                "and growth efficiency (high growth at reasonable P/S). Profitability is NOT "
                "required. Focus on growth trajectory, market position, and long-term dominance."
            )
        else:
            role = (
                "You are identifying SLEEPER stocks — profitable, under-the-radar companies "
                "with strong moats that Wall Street hasn't fully valued. Key signals: high ROE "
                "and ROIC (management quality), strong FCF margin (real earnings), low P/E "
                "relative to peers, and consistent revenue growth. Prioritize durable competitive "
                "advantages: brand loyalty, switching costs, niche dominance, or network effects. "
                "Positive price momentum rules out value traps."
            )

        user = (
            f"CANDIDATES (pre-screened and ranked by multi-factor model):\n{data_str}\n\n"
            f"{role}\n\n"
            "Select the TOP 10 picks. For each, write a specific 2-3 sentence thesis on WHY "
            "this company could be a life-changing investment. Reference the actual numbers. "
            "Be specific about the business model, competitive moat, and growth catalyst.\n\n"
            "Return ONLY a JSON array:\n"
            '[{"ticker":"XXXX","name":"Full Company Name",'
            '"thesis":"2-3 sentence thesis referencing specific metrics",'
            '"key_metric":"Single most compelling number e.g. 67% revenue growth [↑ACCEL]",'
            '"catalyst":"Specific trigger that could make this stock 5-10x",'
            '"risk":"Main risk to this thesis"}]'
        )

        system = (
            "You are an elite hedge fund analyst identifying high-conviction long-term stock picks. "
            "Be specific, data-driven, and contrarian where warranted. No generic platitudes. "
            "Revenue acceleration and price momentum are strong signals — flag them explicitly. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )

        raw = analyst._call(system, user, max_tokens=3500)

        import re as _re
        clean = _re.sub(r'^```[a-z]*\n?', '', raw.strip(), flags=_re.MULTILINE)
        clean = _re.sub(r'\n?```$', '', clean.strip()).strip()

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
    """Fetches fundamentals, scores with multi-factor model, calls Claude."""
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

        # Phase 2: add derived signals, then score with multi-factor model
        _add_derived_signals(fundamentals)

        compounder_pool = [
            d for d in fundamentals
            if (d.get("revenue_growth") or 0) > 0.05 and (d.get("gross_margin") or 0) > 0.2
        ]
        sleeper_pool = [
            d for d in fundamentals
            if (d.get("pe") or 0) > 2 and (d.get("pe") or 0) < 60
        ]

        compounder_scores = _build_compounder_scores(compounder_pool)
        sleeper_scores    = _build_sleeper_scores(sleeper_pool)

        top_compounders = sorted(
            compounder_pool, key=lambda d: -compounder_scores.get(d["ticker"], 0)
        )[:35]
        top_sleepers = sorted(
            sleeper_pool, key=lambda d: -sleeper_scores.get(d["ticker"], 0)
        )[:35]

        with _lock:
            _state["progress"] = 0.70

        # Phase 3: enrich finalists with name/sector, insider activity, short interest
        all_finalists = {d["ticker"]: d for d in top_compounders + top_sleepers}
        unique_finalists = list(all_finalists.values())
        for i, d in enumerate(unique_finalists):
            ticker = d["ticker"]

            # Company name and sector (Finnhub profile, rate-limited)
            try:
                from services.finnhub_client import get_company_profile
                profile = _rate_limited_call(get_company_profile, ticker)
                if profile:
                    d["name"] = profile.get("name", ticker)
                    d["sector"] = profile.get("finnhubIndustry", "Unknown")
            except Exception:
                pass

            # Insider buying/selling signal (Finnhub, rate-limited)
            try:
                from services.finnhub_client import get_insider_sentiment
                insider = _rate_limited_call(get_insider_sentiment, ticker)
                if insider:
                    d["insider_signal"] = insider.get("signal", "neutral")
                    d["insiders_buying"] = insider.get("insiders_buying", 0)
                    d["insiders_selling"] = insider.get("insiders_selling", 0)
            except Exception:
                pass

            # Short interest (Polygon — independent rate limit, fully optional)
            try:
                from services.polygon_client import get_short_data
                short = get_short_data(ticker)
                if short:
                    d["days_to_cover"] = short.get("days_to_cover")
                    d["short_vol_pct"] = short.get("short_volume_ratio_pct")
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
                rev_g = d.get("revenue_growth") or 0
                rev_q = d.get("revenue_growth_q")
                enriched.append({
                    "ticker": t,
                    "name": p.get("name") or d.get("name", t),
                    "sector": d.get("sector", ""),
                    "thesis": p.get("thesis", ""),
                    "key_metric": p.get("key_metric", ""),
                    "catalyst": p.get("catalyst", ""),
                    "risk": p.get("risk", ""),
                    # Core metrics
                    "market_cap_b": round((d.get("market_cap") or 0) / 1000, 2),
                    "revenue_growth_pct": round(rev_g * 100, 1),
                    "gross_margin_pct": round((d.get("gross_margin") or 0) * 100, 1),
                    "pe": round(d.get("pe"), 1) if (d.get("pe") or 0) > 0 else None,
                    "ps": round(d.get("ps"), 1) if d.get("ps") else None,
                    "roe_pct": round((d.get("roe") or 0) * 100, 1),
                    # New multi-factor metrics
                    "fcf_margin_pct": round((d.get("fcf_margin") or 0) * 100, 1) if d.get("fcf_margin") is not None else None,
                    "roic_pct": round((d.get("roic") or 0) * 100, 1) if d.get("roic") else None,
                    "return_6m_pct": round(d.get("return_6m") or 0, 1) if d.get("return_6m") is not None else None,
                    "rev_accel_pct": round((rev_q - rev_g) * 100, 1) if rev_q is not None else None,
                    # Insider and short signals
                    "insider_signal": d.get("insider_signal", "neutral"),
                    "insiders_buying": d.get("insiders_buying") or 0,
                    "insiders_selling": d.get("insiders_selling") or 0,
                    "days_to_cover": d.get("days_to_cover"),
                    "short_vol_pct": d.get("short_vol_pct"),
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
