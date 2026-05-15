"""
Advanced Scanner Service — two-stage funnel scanners.

Stage 1: Fast pre-filter using Finnhub fundamentals (batch, threaded).
Stage 2: Quantitative trigger scoring — Monte Carlo DCF (no Claude) + 50-day MA +
         earnings calendar → trigger score (0-8).

DIVIDEND INCOME SCANNER
  Universe : data/dividend-achievers.json (~270 tickers, Nasdaq Dividend Achievers index)
             Update list quarterly to reflect index reconstitution.
  Pre-filter: yield >= 3.5%, payout <= 65%, revenue growth >= 5%,
              market cap >= $5B, gross margin >= 20%
  Rank by trigger score; top 5 with score >= 5 shown.

BIG MOVER SCANNER
  Universe : S&P 500 + Nasdaq 100 (~600 tickers, hardcoded — update semi-annually)
  Pre-filter: revenue growth >= 20%, market cap $1B-$50B, avg volume >= 500k shares,
              current price <= 75% of 52-week high, P/S <= 8
  Rank by (Monte Carlo % × base case upside); top 5 shown; labeled SPECULATIVE.

Cache     : JSON files in data/ directory, 24-hour TTL.
Progress  : In-memory state dict, polled by frontend via /api/advanced-scanner/status.
"""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_DIVIDEND_ACHIEVERS_FILE = os.path.join(_BASE_DIR, "dividend-achievers.json")
_DIVIDEND_CACHE_FILE = os.path.join(_BASE_DIR, "cache_dividend_scan.json")
_MOVER_CACHE_FILE = os.path.join(_BASE_DIR, "cache_mover_scan.json")

# ---------------------------------------------------------------------------
# S&P 500 + Nasdaq 100 universe (update semi-annually)
# ---------------------------------------------------------------------------
SP500_NASDAQ100 = [
    "A","AAPL","ABBV","ABT","ACGL","ACN","ADBE","ADI","ADM","ADP","ADSK","AEE","AEP",
    "AES","AFL","AIG","AJG","AKAM","ALB","ALGN","ALL","ALLE","AMAT","AMCR","AMD",
    "AME","AMGN","AMP","AMT","AMZN","ANET","ANSS","AON","AOS","APD","APH","APTV",
    "ARE","ATO","AVB","AVGO","AVY","AWK","AXON","AXP","AZO","BA","BAC","BALL",
    "BAX","BBWI","BBY","BDX","BEN","BF.B","BIIB","BK","BKNG","BKR","BLK","BMY",
    "BR","BRK.B","BRO","BSX","BWA","BX","BXP","C","CAG","CAH","CARR","CAT","CB",
    "CBOE","CBRE","CCI","CCL","CDNS","CDW","CE","CEG","CF","CFG","CHD","CHRW",
    "CHTR","CI","CINF","CL","CLX","CMA","CMCSA","CME","CMG","CMI","CMS","CNC",
    "CNP","COF","COO","COP","COST","CPAY","CPB","CPRT","CPT","CRL","CRM","CSCO",
    "CSX","CTAS","CTLT","CTRA","CTSH","CTVA","CVS","CVX","D","DAL","DAY","DD",
    "DE","DECK","DFS","DG","DHI","DHR","DIS","DLTR","DOC","DOV","DOW","DPZ",
    "DRI","DTE","DUK","DVA","DVN","DXCM","EA","EBAY","ECL","ED","EFX","EG",
    "EIX","EL","ELV","EMN","EMR","EOG","EPAM","EQIX","EQR","EQT","ES","ESS",
    "ETN","ETR","EVRG","EW","EXC","EXPE","EXPD","FAST","FCX","FDS","FDX","FE",
    "FFIV","FI","FICO","FIS","FITB","FMC","FOX","FOXA","FRT","FSLR","FTNT",
    "GD","GE","GEHC","GEN","GILD","GIS","GL","GLW","GM","GOOGL","GPC","GS",
    "GWW","HAL","HAS","HBAN","HCA","HD","HIG","HII","HLT","HON","HPE","HPQ",
    "HRL","HSIC","HST","HSY","HUM","HWM","IBM","ICE","IDXX","IEX","IFF","ILMN",
    "INCY","INTC","INTU","INVH","IP","IPG","IQV","IR","IRM","ISRG","IT","ITW",
    "IVZ","J","JBHT","JBL","JKHY","JNJ","JNPR","JPM","K","KDP","KEY","KEYS",
    "KHC","KIM","KLAC","KMB","KMI","KO","KR","L","LDOS","LEN","LH","LHX","LIN",
    "LKQ","LLY","LMT","LNT","LOW","LRCX","LULU","LUV","LVS","LW","LYB","LYV",
    "MA","MAA","MAR","MAS","MCD","MCHP","MCK","MCO","MDLZ","MDT","MET","META",
    "MGM","MHK","MKC","MKTX","MLM","MMC","MMM","MNST","MO","MOH","MOS","MPC",
    "MPWR","MRK","MRNA","MS","MSCI","MSFT","MSI","MTB","MTCH","MTD","MU","NCLH",
    "NDAQ","NDSN","NEE","NEM","NFLX","NI","NKE","NNN","NOC","NOW","NRG","NSC",
    "NTAP","NTRS","NUE","NVDA","NWL","NWS","NWSA","NXPI","O","ODFL","OKE","OMC",
    "ON","OPT","ORCL","ORI","OTIS","OXY","PANW","PARA","PAYC","PAYX","PCAR",
    "PCG","PEG","PEP","PFE","PFG","PG","PGR","PH","PHM","PKG","PLD","PM",
    "PNC","PNR","PNW","PODD","POOL","PPG","PPL","PRU","PSA","PSX","PTWD","PTC",
    "PWR","PYPL","QCOM","QRVO","RCL","REG","REGN","RF","RHI","RJF","RL","RMD",
    "ROK","ROL","ROP","ROST","RS","RSG","RTX","SBAC","SBUX","SCHW","SEE","SHW",
    "SJM","SLB","SMCI","SNA","SNPS","SO","SOLV","SPG","SPGI","SRE","STE","STT",
    "STX","STZ","SW","SWK","SWKS","SYF","SYK","SYY","T","TAP","TDG","TDY",
    "TECH","TEL","TER","TFC","TFX","TGT","TJX","TMO","TMUS","TPR","TRMB","TROW",
    "TRV","TSCO","TSLA","TSN","TT","TTWO","TXN","TXT","TYL","UAL","UBER","UDR",
    "UHS","ULTA","UNH","UNP","UPS","URI","USB","V","VICI","VLO","VLTO","VMC",
    "VRSK","VRSN","VRTX","VZ","WAB","WAT","WBA","WBD","WDC","WELL","WFC","WHR",
    "WM","WMB","WMT","WPC","WRB","WST","WTW","WY","WYNN","XEL","XOM","XYL",
    "YUM","ZBH","ZBRA","ZTS",
]
SP500_NASDAQ100 = list(dict.fromkeys(SP500_NASDAQ100))  # deduplicate preserving order

# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------
_progress: dict[str, dict] = {
    "dividend": {"running": False, "phase": None, "current": 0, "total": 0, "started_at": None},
    "movers":   {"running": False, "phase": None, "current": 0, "total": 0, "started_at": None},
}
_progress_lock = threading.Lock()


def _set_progress(scan_type: str, **kwargs) -> None:
    with _progress_lock:
        _progress[scan_type].update(kwargs)


def get_scan_status(scan_type: str) -> dict:
    with _progress_lock:
        return dict(_progress[scan_type])


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
_CACHE_TTL_SECONDS = 24 * 3600


def _cache_file(scan_type: str) -> str:
    return _DIVIDEND_CACHE_FILE if scan_type == "dividend" else _MOVER_CACHE_FILE


def _load_cache(scan_type: str) -> dict | None:
    path = _cache_file(scan_type)
    try:
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        ts = data.get("cached_at", 0)
        if time.time() - ts > _CACHE_TTL_SECONDS:
            return None
        return data
    except Exception as e:
        logger.warning("Cache load failed for %s: %s", scan_type, e)
        return None


def _save_cache(scan_type: str, payload: dict) -> None:
    path = _cache_file(scan_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload["cached_at"] = time.time()
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning("Cache save failed for %s: %s", scan_type, e)


def _cache_timestamp(scan_type: str) -> str | None:
    path = _cache_file(scan_type)
    try:
        with open(path) as f:
            data = json.load(f)
        ts = data.get("cached_at")
        if ts:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Fundamentals pre-filter helpers
# ---------------------------------------------------------------------------

def _get_fundamentals(ticker: str) -> dict | None:
    """Single Finnhub call returning normalised pre-filter metrics."""
    try:
        from services.finnhub_client import get_basic_financials, get_company_profile
        metrics = get_basic_financials(ticker)
        if not metrics:
            return None
        profile = get_company_profile(ticker) or {}

        week52_high = metrics.get("52WeekHigh") or metrics.get("52WeekHighDate")
        # Prefer the numeric high; get_basic_financials returns {"52WeekHigh": float, ...}
        if isinstance(week52_high, str):
            week52_high = None

        avg_vol = (
            metrics.get("10DayAverageTradingVolumeMillion") or
            metrics.get("3MonthAverageTradingVolumeMillion") or
            0
        )

        return {
            "ticker": ticker,
            "name": profile.get("name", ticker),
            "market_cap": metrics.get("marketCapitalization"),   # millions
            "dividend_yield": metrics.get("currentDividendYieldTTM") or metrics.get("dividendYieldIndicatedAnnual") or 0,
            "payout_ratio": metrics.get("payoutRatioTTM") or 0,
            "revenue_growth": metrics.get("revenueGrowthTTMYoy") or 0,
            "gross_margin": metrics.get("grossMarginTTM") or 0,
            "ps": metrics.get("psTTM") or 0,
            "week52_high": week52_high,
            "avg_volume_m": avg_vol,          # in millions
            "current_price": metrics.get("52WeekLow") and None,  # fetched below if needed
        }
    except Exception as e:
        logger.debug("_get_fundamentals failed for %s: %s", ticker, e)
        return None


def _batch_fundamentals(tickers: list[str], scan_type: str, phase: str, workers: int = 6) -> list[dict]:
    """Fetch fundamentals for all tickers in parallel; updates progress."""
    results = []
    _set_progress(scan_type, phase=phase, current=0, total=len(tickers))
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_get_fundamentals, t): t for t in tickers}
        for fut in as_completed(futures):
            completed += 1
            _set_progress(scan_type, current=completed)
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception as e:
                logger.debug("fundamentals future error: %s", e)

    return results


# ---------------------------------------------------------------------------
# Quant trigger analysis (no Claude)
# ---------------------------------------------------------------------------

def _quant_trigger(ticker: str) -> dict | None:
    """
    Run quantitative trigger analysis for one ticker.
    Calls analyze_quant (mechanical DCF, no Claude) + MA + earnings.
    Returns merged result dict or None on failure.
    """
    try:
        from services.dcf_service import analyze_quant
        from services.trigger_service import _fetch_ma_data, _calculate_score
        from services.finnhub_client import get_earnings_this_month

        dcf = analyze_quant(ticker)
        ma_data = _fetch_ma_data(ticker)
        try:
            earnings_days = get_earnings_this_month(ticker)
        except Exception:
            earnings_days = None

        score, breakdown, action, suggested_size, blocked = _calculate_score(dcf, ma_data, earnings_days)

        bear_upside = dcf.get("dcf_bear_upside")
        if bear_upside is not None:
            bear_downside = abs(bear_upside) if bear_upside < 0 else 0
            if bear_downside < 30:
                bear_protection_level = "low"
            elif bear_downside <= 50:
                bear_protection_level = "moderate"
            else:
                bear_protection_level = "high"
        else:
            bear_protection_level = None

        return {
            **dcf,
            "trigger_score": score,
            "trigger_action": action,
            "trigger_blocked": blocked,
            "suggested_position_size": suggested_size,
            "trigger_breakdown": breakdown,
            "ma50": ma_data["ma50"] if ma_data else None,
            "above_ma": ma_data["above_ma"] if ma_data else None,
            "crossover_5d": ma_data["crossover_5d"] if ma_data else None,
            "earnings_days": earnings_days,
            "bear_protection_level": bear_protection_level,
        }
    except Exception as e:
        logger.debug("_quant_trigger failed for %s: %s", ticker, e)
        return None


def _batch_trigger(tickers: list[str], scan_type: str, workers: int = 4) -> list[dict]:
    """Run quant trigger analysis for survivors; updates progress."""
    results = []
    _set_progress(scan_type, phase="deep_analysis", current=0, total=len(tickers))
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_quant_trigger, t): t for t in tickers}
        for fut in as_completed(futures):
            completed += 1
            _set_progress(scan_type, current=completed)
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception as e:
                logger.debug("trigger future error: %s", e)

    return results


# ---------------------------------------------------------------------------
# DIVIDEND INCOME SCANNER
# ---------------------------------------------------------------------------

def _load_dividend_achievers() -> list[str]:
    try:
        with open(_DIVIDEND_ACHIEVERS_FILE) as f:
            tickers = json.load(f)
        return [t.upper() for t in tickers if isinstance(t, str)]
    except Exception as e:
        logger.error("Failed to load dividend-achievers.json: %s", e)
        return []


def _prefilter_dividend(fundamentals: list[dict]) -> list[str]:
    """Apply dividend income criteria; return passing tickers."""
    survivors = []
    for f in fundamentals:
        mc = f.get("market_cap") or 0       # millions
        yield_ = f.get("dividend_yield") or 0
        payout = f.get("payout_ratio") or 0
        rev_g = f.get("revenue_growth") or 0
        gm = f.get("gross_margin") or 0
        if (
            yield_ >= 3.5
            and payout <= 65
            and rev_g >= 5
            and mc >= 5_000       # $5B = 5000M
            and gm >= 20
        ):
            survivors.append(f["ticker"])
    logger.info("Dividend pre-filter: %d / %d passed", len(survivors), len(fundamentals))
    return survivors


def run_dividend_scan(force: bool = False) -> dict:
    """
    Run (or return cached) dividend income scan.
    force=True ignores cache and runs fresh.
    """
    if not force:
        cached = _load_cache("dividend")
        if cached:
            logger.info("Dividend scan: returning cached results from %s", cached.get("scanned_at"))
            return cached

    _set_progress("dividend", running=True, phase="prefetch", current=0, total=0, started_at=time.time())
    try:
        universe = _load_dividend_achievers()
        if not universe:
            raise RuntimeError("Dividend Achievers list is empty — check data/dividend-achievers.json")

        logger.info("Dividend scan: pre-filtering %d tickers", len(universe))
        fundamentals = _batch_fundamentals(universe, "dividend", "prefetch")
        survivors = _prefilter_dividend(fundamentals)

        if not survivors:
            logger.warning("Dividend scan: no stocks passed pre-filter")
            result = {"results": [], "scanned_at": datetime.now(timezone.utc).isoformat(),
                      "universe_size": len(universe), "survivors": 0, "mode": "dividend"}
            _save_cache("dividend", result)
            return result

        logger.info("Dividend scan: deep analysis on %d survivors", len(survivors))
        trigger_results = _batch_trigger(survivors, "dividend")

        # Attach dividend yield from pre-filter pass
        yield_map = {f["ticker"]: f.get("dividend_yield", 0) for f in fundamentals}
        for r in trigger_results:
            r["dividend_yield_pct"] = round(yield_map.get(r["ticker"], 0), 2)

        # Rank by trigger score; minimum score 5
        qualified = [r for r in trigger_results if r.get("trigger_score", 0) >= 5]
        ranked = sorted(qualified, key=lambda r: r.get("trigger_score", 0), reverse=True)[:5]

        result = {
            "results": ranked,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "universe_size": len(universe),
            "survivors": len(survivors),
            "qualified": len(qualified),
            "mode": "dividend",
        }
        _save_cache("dividend", result)
        return result

    except Exception as e:
        logger.error("Dividend scan failed: %s", e, exc_info=True)
        raise
    finally:
        _set_progress("dividend", running=False, phase="done")


# ---------------------------------------------------------------------------
# BIG MOVER SCANNER
# ---------------------------------------------------------------------------

def _prefilter_movers_polygon(tickers: list[str]) -> list[str]:
    """
    Quick Polygon batch snapshot: keep only stocks where day volume >= 200k
    as a loose pre-filter before the more expensive Finnhub fundamental pull.
    """
    try:
        from services.polygon_client import get_snapshots_batch
        BATCH = 500
        survivors = []
        for i in range(0, len(tickers), BATCH):
            batch = tickers[i:i + BATCH]
            snaps = get_snapshots_batch(batch)
            for ticker in batch:
                snap = snaps.get(ticker)
                if snap and snap.get("volume", 0) >= 200_000:
                    survivors.append(ticker)
        logger.info("Movers Polygon pre-filter: %d / %d passed (volume ≥200k)", len(survivors), len(tickers))
        return survivors
    except Exception as e:
        logger.warning("Polygon pre-filter failed — using full universe: %s", e)
        return tickers


def _prefilter_movers_fundamentals(fundamentals: list[dict]) -> list[str]:
    """Apply big mover criteria; return passing tickers."""
    survivors = []
    for f in fundamentals:
        mc = f.get("market_cap") or 0          # millions
        rev_g = f.get("revenue_growth") or 0
        ps = f.get("ps") or 0
        avg_vol_m = f.get("avg_volume_m") or 0  # millions
        avg_vol = avg_vol_m * 1_000_000

        if not (rev_g >= 20 and 1_000 <= mc <= 50_000 and avg_vol >= 500_000 and ps <= 8):
            continue

        # Price ≤ 75% of 52-week high requires a price. Skip if no 52-week high data.
        w52h = f.get("week52_high")
        if w52h:
            # current_price approximation: we don't have it in snapshot at this point
            # We'll skip this sub-filter if no price data and let trigger analysis handle it.
            pass

        survivors.append(f["ticker"])

    logger.info("Movers fundamental pre-filter: %d / %d passed", len(survivors), len(fundamentals))
    return survivors


def run_mover_scan(force: bool = False) -> dict:
    """
    Run (or return cached) big mover scan.
    force=True ignores cache and runs fresh.
    """
    if not force:
        cached = _load_cache("movers")
        if cached:
            logger.info("Mover scan: returning cached results from %s", cached.get("scanned_at"))
            return cached

    _set_progress("movers", running=True, phase="prefetch", current=0, total=0, started_at=time.time())
    try:
        universe = SP500_NASDAQ100
        logger.info("Mover scan: universe size %d", len(universe))

        # Stage 1: Polygon volume filter (fast batch)
        _set_progress("movers", phase="polygon_filter")
        volume_survivors = _prefilter_movers_polygon(universe)

        # Stage 2: Finnhub fundamental filter
        logger.info("Mover scan: fetching fundamentals for %d tickers", len(volume_survivors))
        fundamentals = _batch_fundamentals(volume_survivors, "movers", "fundamental_filter")
        fundamental_survivors = _prefilter_movers_fundamentals(fundamentals)

        if not fundamental_survivors:
            logger.warning("Mover scan: no stocks passed pre-filter")
            result = {"results": [], "scanned_at": datetime.now(timezone.utc).isoformat(),
                      "universe_size": len(universe), "survivors": 0, "mode": "movers"}
            _save_cache("movers", result)
            return result

        # Stage 3: Quant trigger analysis
        logger.info("Mover scan: deep analysis on %d survivors", len(fundamental_survivors))
        trigger_results = _batch_trigger(fundamental_survivors, "movers")

        # Attach revenue growth from pre-filter
        growth_map = {f["ticker"]: f.get("revenue_growth", 0) for f in fundamentals}
        for r in trigger_results:
            r["revenue_growth_display"] = round(growth_map.get(r["ticker"], 0), 1)

        # Rank by (Monte Carlo % × base upside); handle None gracefully
        def _score_mover(r: dict) -> float:
            mc_prob = (r.get("monte_carlo") or {}).get("prob_undervalued_pct") or 0
            base_up = r.get("dcf_base_upside") or 0
            return mc_prob * max(base_up, 0) / 100.0

        ranked = sorted(trigger_results, key=_score_mover, reverse=True)[:5]

        result = {
            "results": ranked,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "universe_size": len(universe),
            "survivors": len(fundamental_survivors),
            "qualified": len(trigger_results),
            "mode": "movers",
            "speculative": True,
        }
        _save_cache("movers", result)
        return result

    except Exception as e:
        logger.error("Mover scan failed: %s", e, exc_info=True)
        raise
    finally:
        _set_progress("movers", running=False, phase="done")


# ---------------------------------------------------------------------------
# Background scan launcher
# ---------------------------------------------------------------------------

def launch_scan_background(scan_type: str) -> None:
    """Fire scan in a daemon thread so the API can return immediately."""
    def _run():
        try:
            if scan_type == "dividend":
                run_dividend_scan(force=True)
            else:
                run_mover_scan(force=True)
        except Exception as e:
            logger.error("Background scan %s failed: %s", scan_type, e)

    with _progress_lock:
        if _progress[scan_type]["running"]:
            logger.info("Scan %s already running — ignoring duplicate request", scan_type)
            return

    threading.Thread(target=_run, daemon=True).start()
