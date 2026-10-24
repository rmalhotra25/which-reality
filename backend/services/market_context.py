"""
Fetches VIX + SPY data and classifies the current market regime.
- SPY: via Finnhub (primary), Polygon aggs (secondary)
- VIX: via Polygon index aggregates (primary), yfinance as fallback
Results cached in-memory for 30 minutes, and never served older than
2 hours: past 2 hours a failed refresh forces UNKNOWN instead of
serving stale context.

Verdict rules (see _trade_verdict and verdict_for_direction):
- Missing VIX can never GREEN-light trades: VIX must be present and
  fresh, and SPY data must be complete, for GREEN.
- YELLOW is a caution badge, not a gate: it blocks nothing on its own.
  In a BEAR regime calls are against-regime (badged) and puts are
  favoured; in a RED (volatile) regime calls are suppressed while puts
  are allowed, flagged as caution, as a hedge or speculation only.
- MA200 requires 200 closes; with fewer closes the regime is unknown.
"""
import logging
import time
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 1800  # 30 minutes
CACHE_MAX_AGE = 7200  # 2 hours: past this, stale context is never served


def get_market_context(force_refresh: bool = False) -> dict:
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        data = _fetch()
    except Exception as e:
        logger.warning("market_context fetch failed: %s", e)
        if _cache["data"] and (now - _cache["ts"]) <= CACHE_MAX_AGE:
            logger.warning("market_context serving cached context %.0f seconds old", now - _cache["ts"])
            return _cache["data"]
        return _unavailable()

    _cache["data"] = data
    _cache["ts"] = now
    return data


def _ma_from_closes(closes: list, window: int) -> float | None:
    """Mean of the last `window` closes, or None when fewer closes exist.

    A moving average is never computed from a short window: MA200 needs
    200 closes, MA50 needs 50 closes.
    """
    if not closes or len(closes) < window:
        return None
    return float(sum(closes[-window:]) / window)


def _is_fresh(as_of: date | None, max_age_days: int = 4) -> bool:
    """True when the as-of date of the last bar is recent enough to trust.

    Four days covers a long weekend (Friday bar still fresh on Monday);
    anything older is stale data, not a current read.
    """
    if as_of is None:
        return False
    return (date.today() - as_of).days <= max_age_days


def _fetch() -> dict:
    vix, vix_as_of = _fetch_vix()
    spy_price, ma50, ma200, spy_as_of = _fetch_spy()

    # Stale bars are treated as missing data, never as a current read.
    if not _is_fresh(spy_as_of):
        spy_price, ma50, ma200 = None, None, None
    if not _is_fresh(vix_as_of):
        vix = None

    spy_vs_50 = round((spy_price / ma50 - 1) * 100, 1) if spy_price and ma50 else None
    spy_vs_200 = round((spy_price / ma200 - 1) * 100, 1) if spy_price and ma200 else None

    # data_complete is True only when we have enough to classify the regime
    data_complete = bool(spy_price and ma50 and ma200)

    regime = _classify_regime(vix, spy_price, ma50, ma200)
    verdict = _trade_verdict(vix, regime, data_complete)
    vix_label = _vix_label(vix)

    return {
        "vix": round(vix, 2) if vix is not None else None,
        "vix_label": vix_label,
        "vix_as_of_date": vix_as_of.isoformat() if vix_as_of else None,
        "spy_price": round(spy_price, 2) if spy_price is not None else None,
        "spy_as_of_date": spy_as_of.isoformat() if spy_as_of else None,
        "spy_vs_50ma_pct": spy_vs_50,
        "spy_vs_200ma_pct": spy_vs_200,
        "market_regime": regime,
        "trade_verdict": verdict,
        "data_complete": data_complete,
        "summary": _summary(vix, vix_label, spy_price, spy_vs_50, spy_vs_200, regime, verdict),
        "strategy_guidance": _strategy_guidance(vix, regime, vix_label),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "available": True,
    }


def _fetch_vix() -> tuple[float | None, date | None]:
    """VIX via Polygon index aggregates, yfinance as fallback.

    Returns (vix, as-of date of the last VIX bar). The Polygon helper
    returns only the level, so its as-of date is today (the latest daily
    bar); the yfinance path returns the actual last bar date.
    """
    try:
        from services.polygon_client import get_vix
        v = get_vix()
        if v:
            return v, date.today()
    except Exception:
        pass
    # Fallback: yfinance
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="5d")
        if not hist.empty:
            as_of = hist.index[-1].date() if hasattr(hist.index[-1], "date") else None
            return float(hist["Close"].iloc[-1]), as_of
    except Exception as e:
        logger.debug("VIX yfinance fallback failed: %s", e)
    return None, None


def _fetch_spy() -> tuple[float | None, float | None, float | None, date | None]:
    """SPY price + MA50 + MA200 via Finnhub primary, Polygon secondary.

    Returns (price, ma50, ma200, as-of date of the last SPY bar).
    MA50 needs 50 closes and MA200 needs 200 closes; with fewer closes
    the average is None and the regime is unknown.
    """
    # Primary: Finnhub candles (already in place)
    try:
        from services.finnhub_client import get_candles
        candles = get_candles("SPY", days=300)
        if candles.get("s") == "ok" and candles.get("c"):
            closes = [float(c) for c in candles["c"]]
            price = closes[-1]
            ma50 = _ma_from_closes(closes, 50)
            ma200 = _ma_from_closes(closes, 200)
            as_of = None
            stamps = candles.get("t") or []
            if stamps:
                as_of = datetime.fromtimestamp(int(stamps[-1]), tz=timezone.utc).date()
            return price, ma50, ma200, as_of
    except Exception as e:
        logger.debug("SPY Finnhub fetch failed: %s", e)

    # Secondary: Polygon aggs (dated closes, so staleness is checkable)
    try:
        from services.polygon_client import get_dated_closes
        dated = get_dated_closes("SPY", days=250)
        if dated:
            closes = [float(c) for _, c in dated]
            price = closes[-1]
            ma50 = _ma_from_closes(closes, 50)
            ma200 = _ma_from_closes(closes, 200)
            return price, ma50, ma200, dated[-1][0]
    except Exception as e:
        logger.debug("SPY Polygon fetch failed: %s", e)

    return None, None, None, None


def _unavailable() -> dict:
    return {
        "available": False,
        "data_complete": False,
        "trade_verdict": "UNKNOWN",
        "market_regime": "UNKNOWN",
        "summary": "Market data temporarily unavailable.",
        "strategy_guidance": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _vix_label(vix) -> str:
    if vix is None: return "UNKNOWN"
    if vix < 15:    return "CALM"
    if vix < 25:    return "NORMAL"
    if vix < 35:    return "ELEVATED"
    return "EXTREME"


def _classify_regime(vix, spy_price, ma50, ma200) -> str:
    if vix is not None and vix > 30:
        return "VOLATILE"
    if not (spy_price and ma50 and ma200):
        # Without a real MA200 the trend cannot be classified at all.
        return "UNKNOWN"
    if spy_price > ma50 and ma50 > ma200:
        return "BULL"
    if spy_price < ma50 and spy_price < ma200:
        return "BEAR"
    return "SIDEWAYS"


def _trade_verdict(vix, regime, data_complete: bool = True) -> str:
    """Overall verdict. Missing VIX can never GREEN-light trades: GREEN
    requires a present VIX and complete SPY data."""
    if vix is None:
        return "UNKNOWN"
    if not data_complete:
        return "UNKNOWN"
    if regime == "VOLATILE" or vix > 35:
        return "RED"
    if regime == "BEAR" or vix > 25:
        return "YELLOW"
    return "GREEN"


def verdict_for_direction(overall_verdict: str, regime: str, option_type: str) -> str:
    """Direction-aware verdict for one option type.

    The overall verdict is direction-blind: BEAR gives YELLOW to puts
    that should be favoured, and RED suppresses long puts entirely.
    This maps the overall verdict per direction:
    - UNKNOWN stays UNKNOWN for both sides.
    - RED: calls are suppressed (RED); puts are allowed, flagged as
      caution (YELLOW), as a hedge or speculation only.
    - YELLOW in a BEAR regime: puts are favoured (GREEN), calls are
      against-regime (YELLOW). YELLOW otherwise stays YELLOW.
    - GREEN stays GREEN for both sides.
    """
    opt = (option_type or "").upper()
    if overall_verdict == "UNKNOWN":
        return "UNKNOWN"
    if overall_verdict == "RED":
        return "YELLOW" if opt == "PUT" else "RED"
    if overall_verdict == "YELLOW":
        if regime == "BEAR" and opt == "PUT":
            return "GREEN"
        return "YELLOW"
    return overall_verdict


def direction_allowed(direction_verdict: str) -> bool:
    """True when a candidate with this direction verdict may be emitted."""
    return direction_verdict in ("GREEN", "YELLOW")


def _strategy_guidance(vix, regime, vix_label) -> dict:
    if vix_label in ("ELEVATED", "EXTREME"):
        buying = "AVOID: IV is high, options are expensive. Wait for VIX to drop before buying calls or puts."
    elif regime == "BEAR":
        buying = "CAUTIOUS: Market is in a downtrend. Only buy puts or wait for a clear reversal."
    elif regime == "BULL":
        buying = "GOOD: Trending market favors buying calls on strong momentum setups."
    else:
        buying = "NEUTRAL: Sideways market. Favor spread strategies over naked directional buys."

    if vix_label in ("ELEVATED", "EXTREME"):
        selling = "EXCELLENT: High IV means fat premiums. Best time to run the wheel and sell puts."
    elif regime == "BEAR":
        selling = "CAUTIOUS: Falling stocks can get assigned at a loss. Only sell puts on stocks you're confident in."
    elif regime == "BULL":
        selling = "GOOD: Steady market. Collect premiums with reasonable confidence of staying above your strike."
    else:
        selling = "GOOD: Sideways range means puts have low assignment risk if you pick the right strikes."

    if regime == "BULL":
        lt = "GOOD: Uptrend intact. Continue dollar-cost averaging into quality positions."
    elif regime == "BEAR":
        lt = "CAUTIOUS: Wait for the market to stabilize. Consider adding to income positions gradually."
    elif regime == "VOLATILE":
        lt = "WAIT: High volatility creates panic selling. Watch for a real bottom before adding long-term positions."
    else:
        lt = "NEUTRAL: Range-bound market. Focus on dividend income and avoid speculative growth buys."

    return {"options_buying": buying, "wheel_and_selling": selling, "long_term": lt}


def _summary(vix, vix_label, spy_price, spy_vs_50, spy_vs_200, regime, verdict) -> str:
    vix_str = f"VIX is {vix:.1f} ({vix_label.lower()} fear level)" if vix else "VIX data unavailable"
    spy_str = ""
    if spy_price and spy_vs_50 is not None:
        d1 = "above" if spy_vs_50 >= 0 else "below"
        spy_str = f" The S&P 500 is {abs(spy_vs_50)}% {d1} its 50-day average"
        if spy_vs_200 is not None:
            d2 = "above" if spy_vs_200 >= 0 else "below"
            spy_str += f" and {abs(spy_vs_200)}% {d2} its 200-day average."
        else:
            spy_str += "."
    regime_map = {
        "BULL": "Market is in a bull trend: conditions favor staying invested.",
        "BEAR": "Market is in a downtrend: proceed with extra caution.",
        "VOLATILE": "Market is highly volatile: reduce position sizes and be selective.",
        "SIDEWAYS": "Market is moving sideways: range-bound conditions.",
    }
    verdict_map = {
        "GREEN": "Overall conditions are favorable for trading.",
        "YELLOW": "Exercise caution: scale back position sizes.",
        "RED": "Difficult trading environment: consider standing aside or reducing risk significantly.",
    }
    return f"{vix_str}.{spy_str} {regime_map.get(regime,'')} {verdict_map.get(verdict,'')}".strip()
