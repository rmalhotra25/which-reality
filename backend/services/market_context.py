"""
Fetches VIX + SPY data from yfinance and classifies the current market regime.
Results are cached in-memory for 30 minutes to keep page loads fast.
"""
import logging
import time
from datetime import datetime, timezone

import yfinance as yf

logger = logging.getLogger(__name__)

_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 1800  # 30 minutes


def get_market_context(force_refresh: bool = False) -> dict:
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        data = _fetch()
    except Exception as e:
        logger.warning("market_context fetch failed: %s", e)
        if _cache["data"]:
            return _cache["data"]
        data = _unavailable()

    _cache["data"] = data
    _cache["ts"] = now
    return data


def _fetch() -> dict:
    # ── VIX ──────────────────────────────────────────────────────────────────
    vix_hist = yf.Ticker("^VIX").history(period="5d")
    vix = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else None

    # ── SPY ───────────────────────────────────────────────────────────────────
    spy_hist = yf.Ticker("SPY").history(period="1y")
    spy_price = float(spy_hist["Close"].iloc[-1]) if not spy_hist.empty else None

    ma50 = float(spy_hist["Close"].tail(50).mean()) if len(spy_hist) >= 50 else None
    ma200 = float(spy_hist["Close"].tail(200).mean()) if len(spy_hist) >= 200 else None

    spy_vs_50 = round((spy_price / ma50 - 1) * 100, 1) if spy_price and ma50 else None
    spy_vs_200 = round((spy_price / ma200 - 1) * 100, 1) if spy_price and ma200 else None

    regime = _classify_regime(vix, spy_price, ma50, ma200)
    verdict = _trade_verdict(vix, regime)
    vix_label = _vix_label(vix)

    strategy_guidance = _strategy_guidance(vix, regime, vix_label)
    summary = _summary(vix, vix_label, spy_price, spy_vs_50, spy_vs_200, regime, verdict)

    return {
        "vix": round(vix, 2) if vix is not None else None,
        "vix_label": vix_label,
        "spy_price": round(spy_price, 2) if spy_price is not None else None,
        "spy_vs_50ma_pct": spy_vs_50,
        "spy_vs_200ma_pct": spy_vs_200,
        "market_regime": regime,
        "trade_verdict": verdict,
        "summary": summary,
        "strategy_guidance": strategy_guidance,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "available": True,
    }


def _unavailable() -> dict:
    return {
        "available": False,
        "trade_verdict": "UNKNOWN",
        "market_regime": "UNKNOWN",
        "summary": "Market data temporarily unavailable.",
        "strategy_guidance": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Classification helpers ───────────────────────────────────────────────────

def _vix_label(vix) -> str:
    if vix is None:
        return "UNKNOWN"
    if vix < 15:
        return "CALM"
    if vix < 25:
        return "NORMAL"
    if vix < 35:
        return "ELEVATED"
    return "EXTREME"


def _classify_regime(vix, spy_price, ma50, ma200) -> str:
    if vix is not None and vix > 30:
        return "VOLATILE"
    if spy_price and ma50 and ma200:
        if spy_price > ma50 and ma50 > ma200:
            return "BULL"
        if spy_price < ma50 and spy_price < ma200:
            return "BEAR"
    return "SIDEWAYS"


def _trade_verdict(vix, regime) -> str:
    if regime == "VOLATILE" or (vix is not None and vix > 35):
        return "RED"
    if regime == "BEAR" or (vix is not None and vix > 25):
        return "YELLOW"
    return "GREEN"


def _strategy_guidance(vix, regime, vix_label) -> dict:
    # Options buying (debit): bad when IV is elevated — you pay too much premium
    if vix_label in ("ELEVATED", "EXTREME"):
        buying = "AVOID — IV is high, options are expensive. Wait for VIX to drop before buying calls or puts."
    elif regime == "BEAR":
        buying = "CAUTIOUS — Market is in a downtrend. Only buy puts or wait for a clear reversal."
    elif regime == "BULL":
        buying = "GOOD — Trending market favors buying calls on strong momentum setups."
    else:
        buying = "NEUTRAL — Sideways market. Favor spread strategies over naked directional buys."

    # Options selling / wheel: great when IV is elevated — you collect more premium
    if vix_label in ("ELEVATED", "EXTREME"):
        selling = "EXCELLENT — High IV means fat premiums. Best time to run the wheel and sell puts."
    elif regime == "BEAR":
        selling = "CAUTIOUS — Falling stocks can get assigned at a loss. Only sell puts on stocks you're confident in."
    elif regime == "BULL":
        selling = "GOOD — Steady market. Collect premiums with reasonable confidence of staying above your strike."
    else:
        selling = "GOOD — Sideways range means puts have low assignment risk if you pick the right strikes."

    # Long-term investing
    if regime == "BULL":
        lt = "GOOD — Uptrend intact. Continue dollar-cost averaging into quality positions."
    elif regime == "BEAR":
        lt = "CAUTIOUS — Wait for the market to stabilize. Consider adding to income positions gradually."
    elif regime == "VOLATILE":
        lt = "WAIT — High volatility creates panic selling. Watch for a real bottom before adding long-term positions."
    else:
        lt = "NEUTRAL — Range-bound market. Focus on dividend income and avoid speculative growth buys."

    return {
        "options_buying": buying,
        "wheel_and_selling": selling,
        "long_term": lt,
    }


def _summary(vix, vix_label, spy_price, spy_vs_50, spy_vs_200, regime, verdict) -> str:
    vix_str = f"VIX is {vix:.1f} ({vix_label.lower()} fear level)" if vix else "VIX data unavailable"
    spy_str = ""
    if spy_price and spy_vs_50 is not None:
        direction = "above" if spy_vs_50 >= 0 else "below"
        spy_str = f" The S&P 500 is {abs(spy_vs_50)}% {direction} its 50-day average"
        if spy_vs_200 is not None:
            d2 = "above" if spy_vs_200 >= 0 else "below"
            spy_str += f" and {abs(spy_vs_200)}% {d2} its 200-day average."
        else:
            spy_str += "."

    regime_map = {
        "BULL": "Market is in a bull trend — conditions favor staying invested.",
        "BEAR": "Market is in a downtrend — proceed with extra caution.",
        "VOLATILE": "Market is highly volatile — reduce position sizes and be selective.",
        "SIDEWAYS": "Market is moving sideways — range-bound conditions.",
    }
    regime_str = regime_map.get(regime, "")

    verdict_map = {
        "GREEN": "Overall conditions are favorable for trading.",
        "YELLOW": "Exercise caution — scale back position sizes.",
        "RED": "Difficult trading environment — consider standing aside or reducing risk significantly.",
    }
    verdict_str = verdict_map.get(verdict, "")

    return f"{vix_str}.{spy_str} {regime_str} {verdict_str}".strip()
