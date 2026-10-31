"""
Deterministic ticker lookup (query, not a decision maker).

Type a ticker, get a snapshot. The lookup runs the same rule registry
check on that one ticker, on demand, using the same data sources and
the same thresholds as the alert engine:

- Price, trend, and indicators come from the same OHLCV fetch and the
  same _indicators() as services.alert_engine.
- Every setup in alert_engine._SETUP_EVALUATORS is evaluated by the
  same evaluator function, with the same constants, the same earnings
  fail-closed gate, and the same SPY gate.
- A setup that fires gets its action from alert_engine._build_alert,
  so entry, stop, target or exit rule, strike, size, expiry, and
  invalidation are exactly what the live run would show for that
  ticker at that data timestamp. The result is labelled as the rule
  result for that ticker at that time, not as an instruction to trade.
- Quality is a display-only composite built from existing
  quant_scorer component functions (trend, RSI, volume). It never
  gates a setup and it is not a rule.
- The listed option chain comes from ChainProvider (Polygon primary,
  yfinance fallback), the same provider the directional and wheel
  paths use. Premium at Support still prices from get_listed_put,
  at the bid, or suppresses with a named reason.

What the lookup never does, by construction: it writes no alert
row, creates no journal row, sends no Telegram message, writes no run
receipt, and starts no scheduler job. This module imports none of
those writers. It is a read-only query. Directional Options and
Champions are SHADOW systems evaluated by their own scheduled runs,
so the lookup reports them as not evaluated on demand, with the named
reason, instead of building a second directional or champions system.
The down-market put strategy is SHADOW ONLY and Post-Earnings Drift
is RETIRED; both are reported the same way.

Verdict (build_verdict): the top of the tab is tiered, not binary.
BUY NOW keeps the strict old BUY rule, WAIT FOR ENTRY is a good trend
with no trigger today, AVOID is a broken trend, and CANNOT JUDGE
means a gate or trend input is missing, so no stock judgment is
claimed. The put is offered on BUY NOW as before, and on WAIT FOR
ENTRY only as a discount entry with a 4% cushion floor. The call
stays BUY NOW only. All tiers are computed only from the quant
results above, never by Claude, and BUY NOW has no threshold loosened.

Long-term lane (services.longterm_valuation): a separate verdict
from the timing verdict, computed from the dated quality screener
snapshot and, when reported statements are supplied, a shared-core
DCF. It never changes the timing verdict and never changes put or
call gating. A timing AVOID with a strong long-term lane reads as
a long-term buy candidate to wait for, not as "never buy this
company". When no statements are supplied, the DCF is BLOCKED or
NOT VERIFIED, never derived from market cap divided by P/S.
The stock verdict is based on data, not on setups alone:

- Stock ticker setups that provide conviction: the LIVE setups,
  Quality Pullback and Volume Breakout, plus trend, the display-only
  quality composite, volume, and the SPY gate.
- News and company releases: the live provider fetches recent
  articles from Polygon ticker news (title, published date,
  publisher, url). Only a fresh article, published within 3 days,
  from a press-release wire counts as a company release that
  supports the verdict. Fresh general news is shown as data but
  never counted as support. An article with no date, a fetch
  failure, or no articles at all is recorded as news unavailable,
  and counts for nothing, never as support.
- Anticipated vs actual results: anticipated is the earnings date
  and days away from the Finnhub earnings calendar. Actual is not
  available: the app has no reliable consensus-estimate feed and
  no reliable reported-beat-or-miss feed (Post-Earnings Drift was
  retired for exactly that reason), so the verdict records both as
  missing and never guesses a beat or a miss. A name that reports
  within 5 days is never a BUY, by the same earnings gate that
  blocks every setup, and the verdict says so plainly.
- The conviction summary lists which data actually supported the
  verdict, which data was against it, and which data was missing.
  No factor is invented, and no missing data is counted as support.

Quant decides, Claude explains only (services.ai_boundary): entry,
stop, target, strike, size, rank, score, and grade come only from
quant rules and the listed chain. Claude may write the plain-language
explanation only, through an explain_fn supplied by the caller, and a
Claude failure falls back to a quant-derived sentence without
changing, delaying, or suppressing the quant result.

Unknown values are shown as unknown and fail closed: earnings unknown
blocks every setup (earnings_unknown), IV unavailable blocks Premium
at Support, no listed chain suppresses the options result with the
named reason no_listed_chain. An invalid or unknown ticker raises
LookupError with a named code, never a guessed result.

Results are cached in memory for LOOKUP_CACHE_TTL_SECONDS (120s) by
the lookup_ticker() wrapper only; evaluate_lookup() is pure and
uncached, so the same stubbed inputs always give the same result.
A cached result is labelled cached with its original data timestamp,
and is never served past its TTL.
"""
import copy
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

LOOKUP_CACHE_TTL_SECONDS = 120
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")

# Display names, matching the rule registry rows in
# services.rule_registry (names there carry an "alert" suffix).
_SETUP_NAMES = {
    "quality_pullback": "Quality Pullback",
    "premium_at_support": "Premium at Support",
    "volume_breakout": "Volume Breakout",
    "oversold_bounce": "Oversold Bounce",
    "trend_pullback_reversal": "Trend Pullback Reversal",
    "directional_options": "Directional Options",
    "champions_ai_picks": "Champions AI Picks",
    "directional_puts": "Directional Puts (Down-Market)",
    "post_earnings_drift": "Post-Earnings Drift",
}

# Systems the lookup does not evaluate on demand, with the named reason.
_NOT_EVALUATED = {
    "directional_options": (
        "SHADOW",
        "not_evaluated_on_demand",
        "Directional Options runs on its scheduled weekday 16:30 ET run, "
        "not on demand; the lookup does not build a second directional system.",
    ),
    "champions_ai_picks": (
        "SHADOW",
        "not_evaluated_on_demand",
        "Champions picks run on their scheduled run, not on demand.",
    ),
    "directional_puts": (
        "SHADOW",
        "shadow_only_down_market_puts",
        "Down-market puts are SHADOW ONLY: they lose money on real "
        "backtests (out-of-sample profit factor 0.69).",
    ),
    "post_earnings_drift": (
        "RETIRED",
        "retired_no_reliable_feed",
        "Post-Earnings Drift is RETIRED: no reliable earnings-beat or "
        "guidance feed exists, so it never fires.",
    ),
}


class LookupError(ValueError):
    """A lookup that cannot produce a result, with a named code.

    Codes: invalid_ticker, unknown_ticker, no_data, no_indicators,
    no_listed_chain (chain only; the snapshot itself still returns).
    """

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass
class LookupInputs:
    """Everything evaluate_lookup needs, fetched once by a provider.

    Stub tests build this directly; the live provider builds it from
    the same sources the alert engine uses. A provider that cannot
    fetch price history raises LookupError instead of returning
    half-filled inputs.
    """

    indicators: dict
    data_timestamp: Optional[str] = None
    price_source: str = "yfinance_ohlcv"
    earnings_days: Optional[int] = None
    earnings_date: Optional[str] = None
    iv_percentile: Optional[float] = None
    iv_source: str = "unavailable"
    spy_gate: Optional[bool] = None
    spy_vs_200ma_pct: Optional[float] = None
    chain_puts: list = field(default_factory=list)
    chain_calls: list = field(default_factory=list)
    chain_source: Optional[str] = None
    chain_error: Optional[str] = None
    chain_fetched_at: Optional[str] = None
    # News, from Polygon ticker news via the live provider. Each item
    # is {"title", "published_at", "publisher", "url"}. Stub tests
    # build this directly. Empty means unavailable, never guessed.
    news_items: list = field(default_factory=list)
    news_source: Optional[str] = None
    news_error: Optional[str] = None


def normalize_ticker(raw: str) -> str:
    """Upper-case and validate a ticker. Raises LookupError on bad input."""
    if raw is None:
        raise LookupError("invalid_ticker", "invalid_ticker: no ticker given")
    ticker = str(raw).strip().upper()
    if not ticker or not _TICKER_RE.match(ticker):
        raise LookupError(
            "invalid_ticker",
            f"invalid_ticker: {raw!r} is not a valid ticker symbol",
        )
    # yfinance uses a hyphen where exchanges print a dot (BRK.B -> BRK-B).
    return ticker.replace(".", "-")


def _quality_score(ind: dict, iv_percentile: Optional[float]) -> dict:
    """Display-only quality composite from existing quant_scorer parts.

    Trend 40%, RSI 30%, volume 30%. IV is shown separately and is not
    part of this score. The score never gates a setup.
    """
    from services.ai_boundary import grade_from_quant_score
    from services.quant_scorer import (
        score_moving_averages,
        score_rsi,
        score_volume_trend,
    )

    price = ind.get("price")
    ma50 = ind.get("ma50")
    ma200 = ind.get("ma200")
    trend = score_moving_averages(
        {
            "above_ma50": bool(ma50 is not None and price is not None and price > ma50),
            "above_ma200": bool(ma200 is not None and price is not None and price > ma200),
            "golden_cross": bool(ma50 is not None and ma200 is not None and ma50 > ma200),
            "death_cross": bool(ma50 is not None and ma200 is not None and ma50 < ma200),
        },
        mode="options",
    )
    rsi_score = score_rsi(ind.get("rsi"), mode="trend")
    vol20 = ind.get("vol20")
    volume = ind.get("volume")
    ratio = (volume / vol20) if (volume is not None and vol20) else None
    volume_score = score_volume_trend({"ratio": ratio} if ratio is not None else None)
    composite = round(trend * 0.40 + rsi_score * 0.30 + volume_score * 0.30, 1)
    return {
        "composite": composite,
        "grade": grade_from_quant_score(composite),
        "components": {
            "trend": round(trend, 1),
            "rsi": round(rsi_score, 1),
            "volume": round(volume_score, 1),
        },
        "inputs": {
            "rsi": ind.get("rsi"),
            "volume_ratio_vs_20d": round(ratio, 2) if ratio is not None else None,
            "iv_percentile": iv_percentile,
        },
        "note": "Display only. This score never gates a setup.",
    }


def _trend(ind: dict) -> dict:
    """Price vs 50-day and 200-day MAs, with rising or falling MAs."""
    price = ind.get("price")
    ma50 = ind.get("ma50")
    ma50_lag = ind.get("ma50_lag20")
    ma200 = ind.get("ma200")
    ma200_lag = ind.get("ma200_lag20")
    ma20 = ind.get("ma20")
    return {
        "price": price,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "price_vs_ma50_pct": (
            round((price - ma50) / ma50 * 100, 2)
            if price is not None and ma50 else None
        ),
        "price_vs_ma200_pct": (
            round((price - ma200) / ma200 * 100, 2)
            if price is not None and ma200 else None
        ),
        "above_ma50": bool(price is not None and ma50 is not None and price > ma50),
        "above_ma200": bool(price is not None and ma200 is not None and price > ma200),
        "ma50_direction": (
            "rising" if (ma50 is not None and ma50_lag is not None and ma50 > ma50_lag)
            else "falling" if (ma50 is not None and ma50_lag is not None and ma50 < ma50_lag)
            else "unknown"
        ),
        "ma200_direction": (
            "rising" if (ma200 is not None and ma200_lag is not None and ma200 > ma200_lag)
            else "falling" if (ma200 is not None and ma200_lag is not None and ma200 < ma200_lag)
            else "unknown"
        ),
    }


def _registry_statuses(db) -> dict:
    """rule_key status per alert-engine setup, from the rule registry.

    Returns {} when no db is available; the caller then labels status
    "unknown" and still evaluates, because a lookup is a query, not a
    fire. A RETIRED rule or a rule missing from the registry is never
    evaluated.
    """
    if db is None:
        return {}
    try:
        from services.rule_registry import get_all_rules

        statuses = {}
        for row in get_all_rules(db):
            if row.rule_key.startswith("alert."):
                statuses[row.rule_key[len("alert."):]] = row.status
        return statuses
    except Exception as e:
        logger.debug("ticker_lookup: rule registry read failed: %s", e)
        return {}


def _json_safe(value):
    """Recursively convert a lookup result to plain JSON-native values.

    Live data paths can leak numpy scalars into a conditions dict (a
    numpy bool from a pandas comparison 500s the lookup at FastAPI
    response encoding, because jsonable_encoder cannot serialize it),
    and NaN or inf floats are not valid JSON. Convert numpy scalars
    with .item(), NaN and inf floats to None, and anything else
    unexpected to its string form, so the snapshot always serializes.
    Same inputs still give the same result.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        # float() also strips a numpy float64, which is a float
        # subclass but not a plain Python float.
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            return str(value)
    # Anything else unexpected becomes its string form, so the
    # response still serializes instead of 500ing at encoding.
    return str(value)


# ---------------------------------------------------------------------------
# Verdict: tiered answers, computed only from quant results.
#
# BUY NOW only when at least one LIVE setup (Quality Pullback or
# Volume Breakout) passes, the earnings date is known and more than 5
# days away, and the SPY gate passes. Those gates are already enforced
# by the evaluators; the verdict re-checks them so a setup can never
# produce a BUY on its own if a gate is unknown or blocked. Premium
# at Support is SHADOW, so it never makes a BUY on its own. No
# threshold is loosened for BUY NOW, no new buy signal is invented,
# and no missing data is counted as support. WAIT FOR ENTRY, AVOID,
# and CANNOT JUDGE are not buys: WAIT shows a trigger price, an
# invalidation, a drop and news context, and a dated fundamental
# snapshot when one exists, so the user can judge a dip instead of
# being told only that today is not a buy. News, earnings, trend,
# quality, volume, and the SPY gate are listed in the conviction
# summary as supporting, against, or missing, in plain language.
# ---------------------------------------------------------------------------

_LIVE_STOCK_SETUPS = ("quality_pullback", "volume_breakout")
_NEWS_FRESH_DAYS = 3
# Publishers that carry company press releases. Only a fresh article
# from one of these counts as a company release that supports the
# verdict. Fresh general news is shown as data, never as support.
_PRESS_RELEASE_PUBLISHERS = (
    "globenewswire", "business wire", "pr newswire",
    "prnewswire", "accesswire", "businesswire",
)


def _money(value):
    """Round a per-share price to cents, or None."""
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _delta_abs(row: dict) -> Optional[float]:
    d = row.get("delta_abs")
    if d is not None:
        try:
            return abs(float(d))
        except (TypeError, ValueError):
            return None
    d = row.get("delta")
    if d is not None:
        try:
            return abs(float(d))
        except (TypeError, ValueError):
            return None
    return None


def _spread_pct(row: dict) -> Optional[float]:
    bid = row.get("bid")
    ask = row.get("ask")
    mid = row.get("mid")
    try:
        if bid is not None and ask is not None and mid:
            return round((float(ask) - float(bid)) / float(mid) * 100, 1)
    except (TypeError, ValueError):
        return None
    return None


def _parse_news_date(value):
    """Parse an ISO published_at to a date, or None when unverifiable."""
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _news_verdict(news_items, news_source, news_error, as_of: date) -> dict:
    """Classify the news input for the verdict.

    Returns the latest article with its date and publisher, whether
    it is a fresh company release, and a plain-language note. News
    with no date is unverifiable and counts for nothing. This is
    data only: no sentiment is scored, no headline is summarized
    into a decision, and Claude never touches it.
    """
    items = []
    for row in (news_items or []):
        if not isinstance(row, dict):
            continue
        title = (row.get("title") or "").strip()
        if not title:
            continue
        published = _parse_news_date(row.get("published_at"))
        publisher = (row.get("publisher") or "").strip() or None
        items.append({
            "title": title,
            "published_at": row.get("published_at"),
            "published_date": published.isoformat() if published else None,
            "publisher": publisher,
            "url": row.get("url") or None,
        })
    if not items:
        return {
            "status": "unavailable",
            "source": news_source,
            "error": news_error,
            "latest": None,
            "fresh_company_release": False,
            "note": (
                "No fresh company news or press release could be verified. "
                "News counts for nothing in this verdict."
            ),
        }
    dated = [i for i in items if i["published_date"]]
    latest = dated[0] if dated else items[0]
    if not dated:
        return {
            "status": "unavailable",
            "source": news_source,
            "error": news_error,
            "latest": latest,
            "fresh_company_release": False,
            "note": (
                "News articles were found but none carried a date, so "
                "freshness cannot be verified. News counts for nothing "
                "in this verdict."
            ),
        }
    # Polygon returns newest first, but sort by date to be sure.
    dated.sort(key=lambda i: i["published_date"], reverse=True)
    latest = dated[0]
    days_old = (as_of - date.fromisoformat(latest["published_date"])).days
    publisher_lower = (latest["publisher"] or "").lower()
    is_wire = any(w in publisher_lower for w in _PRESS_RELEASE_PUBLISHERS)
    if days_old < 0:
        days_old = 0
    if days_old <= _NEWS_FRESH_DAYS and is_wire:
        return {
            "status": "fresh_company_release",
            "source": news_source,
            "error": None,
            "latest": latest,
            "fresh_company_release": True,
            "note": (
                f"Fresh company release {days_old} day(s) ago from "
                f"{latest['publisher']}: {latest['title']}"
            ),
        }
    if days_old <= _NEWS_FRESH_DAYS:
        return {
            "status": "fresh_news",
            "source": news_source,
            "error": None,
            "latest": latest,
            "fresh_company_release": False,
            "note": (
                f"Fresh news {days_old} day(s) ago from "
                f"{latest['publisher'] or 'an unknown publisher'}: "
                f"{latest['title']}. Shown as data, not counted as support."
            ),
        }
    return {
        "status": "stale",
        "source": news_source,
        "error": None,
        "latest": latest,
        "fresh_company_release": False,
        "note": (
            f"Latest news is {days_old} day(s) old, from "
            f"{latest['publisher'] or 'an unknown publisher'}. "
            "No fresh company release in the last 3 days."
        ),
    }


def _select_put(price: float, puts: list) -> tuple:
    """Pick the ~0.30-delta put nearest 21 DTE, bid-priced only.

    Same gates as the wheel helper get_listed_put: bid must exist,
    spread at most 15% when known, open interest at least 100 when
    known. Returns (row, None) or (None, (code, plain reason)).
    Never a guessed strike or a last-trade price.
    """
    if not puts:
        return None, ("no_listed_chain",
                      "No listed options chain was available, so no put can be priced.")
    with_bid = []
    for row in puts:
        bid = row.get("bid")
        try:
            bid = float(bid) if bid is not None else None
        except (TypeError, ValueError):
            bid = None
        if bid is not None and bid > 0:
            with_bid.append(row)
    if not with_bid:
        return None, ("no_executable_bid",
                      "No put in the listed chain has a live bid, so no put can be sold.")
    liquid = []
    for row in with_bid:
        spread = _spread_pct(row)
        if spread is not None and spread > 15.0:
            continue
        oi = row.get("open_interest")
        if oi is not None:
            try:
                if float(oi) < 100:
                    continue
            except (TypeError, ValueError):
                pass
        liquid.append(row)
    if not liquid:
        spread_wide = any(
            _spread_pct(r) is not None and _spread_pct(r) > 15.0 for r in with_bid
        )
        if spread_wide:
            return None, ("spread_too_wide",
                          "The put spreads are too wide to sell safely, so no put is offered.")
        return None, ("insufficient_liquidity",
                      "The puts in the listed chain have too little open interest, so no put is offered.")
    def _put_key(row):
        d = _delta_abs(row)
        dte = row.get("dte")
        try:
            dte = float(dte) if dte is not None else 21
        except (TypeError, ValueError):
            dte = 21
        return (
            abs(d - 0.30) if d is not None else 1.0,
            abs(dte - 21),
            abs(float(row.get("strike") or 0) - price),
        )
    return sorted(liquid, key=_put_key)[0], None


def _select_call(price: float, calls: list) -> tuple:
    """Pick the call for the BUY THE CALL answer.

    Rule, reused from the directional engine: listed expiry nearest
    21 DTE, strike snapped to the nearest listed strike above the
    price. Premium is the ask when there is one, else the mid,
    labelled, never a last trade as executable. Returns (row, None)
    or (None, (code, plain reason)).
    """
    if not calls:
        return None, ("no_listed_chain",
                      "No listed options chain was available, so no call can be priced.")
    above = []
    for row in calls:
        try:
            strike = float(row.get("strike") or 0)
        except (TypeError, ValueError):
            continue
        if strike > price:
            above.append(row)
    if not above:
        return None, ("no_call_above_price",
                      "No listed call strike sits above today's price, so no call is offered.")
    def _call_key(row):
        dte = row.get("dte")
        try:
            dte = float(dte) if dte is not None else 21
        except (TypeError, ValueError):
            dte = 21
        return (abs(dte - 21), float(row.get("strike") or 0) - price)
    row = sorted(above, key=_call_key)[0]
    ask = row.get("ask")
    mid = row.get("mid")
    try:
        ask = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask = None
    try:
        mid = float(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid = None
    if ask is not None and ask > 0:
        return row, None
    if mid is not None and mid > 0:
        return row, None
    return None, ("no_executable_ask",
                  "The call above today's price has no live ask or mid, so no call is offered.")


def _what_would_change(qp_cond, vb_cond, earnings_days, spy_gate) -> str:
    """One line, derived from the failing setup conditions, not invented."""
    if earnings_days is None:
        return "Once the next earnings date is known, the setups can be checked again."
    if earnings_days <= 5:
        return "After the earnings report, in a few days, the setups can be checked again."
    if spy_gate is False:
        return "If the wider market closes back above its 200-day average, the gate opens again."
    if spy_gate is None:
        return "Once the wider market trend is known, the gate can be checked again."
    qp = qp_cond or {}
    vb = vb_cond or {}
    if not qp.get("near_ma"):
        return "A pullback to the 50-day or 200-day average on quiet volume would change this."
    if not qp.get("rsi_lt_55"):
        return "A cooler RSI, below 55, after a pullback to an average would change this."
    if not qp.get("quiet_volume"):
        return "A pullback day on quiet volume, below the 20-day average, would change this."
    if not vb.get("above_55d_high"):
        return "A close above the 55-day high on strong volume would change this."
    if not vb.get("vol_confirmed"):
        return "A breakout day with volume at least 1.5 times the 20-day average would change this."
    return "A fresh pullback to an average, or a volume breakout, would change this."


_FUNDAMENTALS_SNAPSHOT = None
_FUNDAMENTALS_SNAPSHOT_LOADED = False


def _load_fundamentals_snapshot() -> dict:
    """Weekly quality screener v2 snapshot, dated 2026-10-26.

    Only survivors are in the file. A ticker absent here is not
    verified in this snapshot, never a failed fundamental. The file
    is loaded once and cached; a missing or unreadable file means
    every ticker is not verified, not guessed.
    """
    global _FUNDAMENTALS_SNAPSHOT, _FUNDAMENTALS_SNAPSHOT_LOADED
    if _FUNDAMENTALS_SNAPSHOT_LOADED:
        return _FUNDAMENTALS_SNAPSHOT or {}
    _FUNDAMENTALS_SNAPSHOT_LOADED = True
    try:
        import json
        import os

        path = os.path.join(
            os.path.dirname(__file__), "..", "data",
            "quality_screener_v2_2026-10-26.json",
        )
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        _FUNDAMENTALS_SNAPSHOT = payload or {}
    except Exception:
        _FUNDAMENTALS_SNAPSHOT = {}
    return _FUNDAMENTALS_SNAPSHOT


def _fundamentals_for(ticker: str, override) -> dict:
    """Fundamentals for one ticker, or a not-verified record.

    An explicit override (from a test, or a newer snapshot) wins.
    Otherwise the dated screener snapshot is used. No fundamental
    is ever invented for a ticker that is not in the snapshot.
    """
    if override is not None:
        if isinstance(override, dict) and override.get("status") == "not_verified":
            return override
        if isinstance(override, dict):
            return {"status": "verified", "run_date": "2026-10-26",
                    "source": "quality_screener_v2", **override}
        return override
    snapshot = _load_fundamentals_snapshot()
    tickers = (snapshot or {}).get("tickers") or {}
    entry = tickers.get((ticker or "").upper())
    if entry is None:
        return {
            "status": "not_verified",
            "run_date": None,
            "source": "quality_screener_v2",
            "note": (
                "This ticker is not in the 2026-10-26 quality screener "
                "v2 survivors, so no fundamental is verified here. "
                "A WAIT verdict never becomes a buy on news alone."
            ),
        }
    return {"status": "verified", "run_date": snapshot.get("run_date"),
            "source": "quality_screener_v2", **entry}


def _classify_news(news: dict) -> dict:
    """Headline category for the latest news item, nothing more.

    Keyword-based, labelled as headline only. A category does not
    prove revenue, margins, or cash flow changed or stayed intact.
    An earnings or guidance headline is flagged as potentially
    fundamental, because the numbers behind it are what matter.
    """
    latest = (news or {}).get("latest") or {}
    title = (latest.get("title") or "").strip()
    title_lower = title.lower()
    if any(k in title_lower for k in ("earnings", "guidance", "outlook",
                                      "quarterly results", "q3 results",
                                      "q4 results", "revenue")):
        category = "earnings_guidance"
        note = (
            "Earnings or guidance headline: treat as potentially "
            "fundamental until the reported numbers are checked. "
            "A headline alone does not prove the thesis changed."
        )
    elif any(k in title_lower for k in ("analyst", "downgrade", "upgrade",
                                        "price target", "rating")):
        category = "analyst"
        note = (
            "Analyst headline: an opinion change, not a company "
            "fundamental by itself. It does not show revenue, "
            "margins, or cash flow changed."
        )
    elif any(k in title_lower for k in ("sector", "industry", "market",
                                        "federal reserve", "interest rate")):
        category = "sector_macro"
        note = (
            "Sector or market headline: a drop on this kind of news "
            "is not by itself a company fundamental break, but it "
            "is also not proof the company is unaffected."
        )
    elif title:
        category = "company_news"
        note = (
            "Company headline, not classified as earnings, analyst, "
            "or sector news. Headline category only: it does not "
            "prove fundamentals changed or stayed intact."
        )
    else:
        category = "none"
        note = "No news headline could be verified, so no news context is claimed."
    return {
        "category": category,
        "title": title or None,
        "published_date": latest.get("published_date"),
        "publisher": latest.get("publisher"),
        "url": latest.get("url"),
        "fresh": bool((news or {}).get("fresh_company_release")),
        "note": note,
    }


def _build_entry_plan(ticker: str, price: float, trend: dict, quality: dict,
                      indicators, qp_cond: dict, vb_cond: dict,
                      earnings_days, earnings_known: bool, spy_gate: dict,
                      news: dict, fundamentals_override) -> dict:
    """WAIT FOR ENTRY detail: trigger, invalidation, and what flips it.

    Every number comes from trend, indicators, or setup conditions.
    Nothing is a target invented for this verdict. The buy zone is
    the range between the 50-day and 200-day averages, where a
    pullback would land, not a price to chase today.
    """
    ind = indicators or {}
    ma50 = trend.get("ma50")
    ma200 = trend.get("ma200")
    prior_high = ind.get("prior_high_55") or (vb_cond or {}).get("prior_high_55")
    prev_close = ind.get("prev_close")
    day_change = None
    if prev_close:
        try:
            day_change = round((price - prev_close) / prev_close * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            day_change = None
    rsi = (quality.get("inputs") or {}).get("rsi")
    if rsi is None:
        rsi = ind.get("rsi")
    vol_ratio = (quality.get("inputs") or {}).get("volume_ratio_vs_20d")
    if vol_ratio is None:
        vol20 = ind.get("vol20")
        vol = ind.get("volume")
        if vol and vol20:
            vol_ratio = round(vol / vol20, 2)
    distance_pullback = None
    if ma50:
        distance_pullback = round((ma50 - price) / price * 100, 2)
    distance_breakout = None
    if prior_high:
        distance_breakout = round((prior_high - price) / price * 100, 2)
    extended = bool(
        (trend.get("price_vs_ma50_pct") is not None
         and trend["price_vs_ma50_pct"] > 10)
        or (rsi is not None and rsi > 75)
    )
    heavy_drop = bool(
        day_change is not None and day_change <= -3
        and vol_ratio is not None and vol_ratio >= 1.5
    )
    blocker = None
    if not earnings_known:
        blocker = "Earnings date unknown, so BUY is blocked until it is known."
    elif earnings_days is not None and earnings_days <= 5:
        blocker = f"Earnings in {earnings_days} day(s), so BUY is blocked until after the report."
    elif spy_gate.get("spy_above_200") is False:
        blocker = "SPY is below its 200-day average, so BUY is blocked until the market closes back above it."
    elif spy_gate.get("spy_above_200") is None:
        blocker = "SPY trend unknown, so BUY is blocked until it is known."
    trigger_parts = []
    if ma50 is not None:
        trigger_parts.append(f"a pullback to the 50-day average at ${round(ma50, 2)}")
    if prior_high is not None:
        trigger_parts.append(f"a close above the 55-day high at ${round(prior_high, 2)}")
    trigger_text = " or ".join(trigger_parts) if trigger_parts else "a fresh pullback or breakout"
    flips_to_buy = (
        f"BUY NOW on {trigger_text} on confirming volume, with earnings "
        "more than 5 days away and SPY above its 200-day average."
    )
    if blocker:
        flips_to_buy += f" Blocker today: {blocker}"
    flips_to_avoid = "A close below the 200-day average would break the trend and flip this to AVOID."
    if ma200 is not None:
        flips_to_avoid = (
            f"A close below ${round(ma200, 2)} would break the trend and flip this to AVOID."
        )
    news_context = _classify_news(news)
    if news_context["category"] == "earnings_guidance":
        flips_to_avoid += " A confirmed guidance cut or earnings miss would also flip it, it is not assumed from a headline alone."
    notes = []
    if extended:
        notes.append(
            "Extended: the price sits well above its 50-day average or RSI is over 75, "
            "so a pullback is the entry, not a chase."
        )
    if heavy_drop:
        notes.append(
            "Heavy volume on a drop of 3% or more: check the news category above "
            "before treating this as a bargain dip."
        )
    if news_context["category"] in ("analyst", "sector_macro"):
        notes.append(
            "Latest headline is analyst or sector news, not an earnings report. "
            "That alone does not show the company fundamental changed."
        )
    return {
        "buy_zone": (
            [round(min(ma50, ma200), 2), round(max(ma50, ma200), 2)]
            if ma50 is not None and ma200 is not None else None
        ),
        "pullback_price": _money(ma50),
        "breakout_price": _money(prior_high),
        "distance_to_pullback_pct": distance_pullback,
        "distance_to_breakout_pct": distance_breakout,
        "invalidation_price": _money(ma200),
        "blocker": blocker,
        "what_flips_to_buy": flips_to_buy,
        "what_flips_to_avoid": flips_to_avoid,
        "drop_context": {
            "day_change_pct": day_change,
            "price_vs_ma50_pct": trend.get("price_vs_ma50_pct"),
            "price_vs_ma200_pct": trend.get("price_vs_ma200_pct"),
            "rsi": round(rsi, 1) if rsi is not None else None,
            "volume_ratio_vs_20d": vol_ratio,
            "extended": extended,
            "heavy_drop": heavy_drop,
        },
        "news_context": news_context,
        "fundamentals": _fundamentals_for(ticker, fundamentals_override),
        "notes": notes,
    }


def build_verdict(ticker: str, *, price: float, setups: list,
                  earnings: dict, spy_gate: dict, quality: dict,
                  trend: dict, iv_percentile, news: dict,
                  chain_puts: list, chain_calls: list,
                  as_of: Optional[date] = None,
                  indicators: Optional[dict] = None,
                  fundamentals: Optional[dict] = None,
                  longterm: Optional[dict] = None,
                  longterm_statements: Optional[dict] = None,
                  longterm_risk_free_rate: Optional[float] = None,
                  longterm_erp: Optional[float] = None) -> dict:
    """Deterministic verdict from quant results only.

    Same inputs give the same verdict. Claude is never called here.
    """
    as_of = as_of or date.today()
    by_key = {s["setup_key"]: s for s in setups}
    qp = by_key.get("quality_pullback") or {}
    vb = by_key.get("volume_breakout") or {}
    live_passing = [
        s for s in setups
        if s.get("setup_key") in _LIVE_STOCK_SETUPS
        and s.get("rule_result") == "pass"
        and s.get("status") == "LIVE"
        and s.get("action")
    ]
    passing = live_passing[0] if live_passing else None
    earnings_days = earnings.get("earnings_days")
    earnings_known = earnings.get("status") == "known"
    earnings_ok = earnings_days is not None and earnings_days > 5
    spy_ok = spy_gate.get("spy_above_200") is True
    spy_below = spy_gate.get("spy_above_200") is False

    supports, against, missing = [], [], []

    # Conviction inputs, each only when the data actually says so.
    if passing:
        supports.append(
            f"A live setup fired today: {passing.get('setup_name')}."
        )
    if trend.get("above_ma50") and trend.get("above_ma200"):
        supports.append("Price is above its 50-day and 200-day averages.")
    if trend.get("ma50_direction") == "rising" and trend.get("ma200_direction") == "rising":
        supports.append("Both the 50-day and 200-day averages are rising.")
    vol_ratio = (quality.get("inputs") or {}).get("volume_ratio_vs_20d")
    if vol_ratio is not None and vol_ratio >= 1.5:
        supports.append(f"Volume is strong, {vol_ratio} times the 20-day average.")
    if earnings_ok:
        supports.append(
            f"Next earnings are known and more than 5 days away "
            f"({earnings.get('earnings_date')})."
        )
    if spy_ok:
        supports.append("The wider market is above its 200-day average.")
    if news.get("fresh_company_release"):
        supports.append(news.get("note") or "Fresh company release in the last 3 days.")

    if not live_passing:
        against.append("No live setup fired today, no pullback and no volume breakout.")
    if not earnings_known:
        against.append("The next earnings date is unknown, so every setup is blocked.")
    elif not earnings_ok:
        against.append(
            f"Earnings are in {earnings_days} day(s), so setups are blocked until after the report."
        )
    if spy_below:
        against.append("The wider market is below its 200-day average, so new buys are blocked.")
    elif not spy_ok and live_passing:
        against.append("The wider market trend is unknown, so new buys are blocked.")
    if trend.get("above_ma50") is False:
        against.append("Price is below its 50-day average.")
    if trend.get("above_ma200") is False:
        against.append("Price is below its 200-day average.")

    # Missing data is listed, never counted as support.
    if not news.get("fresh_company_release"):
        missing.append(news.get("note") or "No fresh company news could be verified.")
    missing.append(
        "No consensus earnings estimate is available, so anticipated results "
        "cannot be compared with actual results."
    )
    missing.append(
        "No reported earnings beat or miss is available. The app has no "
        "reliable beat-or-miss feed, so actual results cannot be scored."
    )
    if iv_percentile is None:
        missing.append("IV rank is unavailable, so the put setup cannot be judged on IV.")

    # Stock verdict, tiered. BUY NOW is unchanged and strict: a live
    # setup fired, earnings known and more than 5 days away, SPY above
    # its 200-day. Everything else is graded, not lumped into one
    # DON'T BUY: WAIT FOR ENTRY (good trend, no trigger today),
    # AVOID (trend broken), or CANNOT JUDGE (a gate or trend input
    # is missing, so no stock judgment is claimed at all).
    can_buy = bool(passing) and earnings_ok and spy_ok
    trend_broken = (
        (trend.get("above_ma200") is False and trend.get("ma200_direction") == "falling")
        or (trend.get("above_ma50") is False and trend.get("above_ma200") is False)
    )
    trend_unknown = trend.get("ma50") is None or trend.get("ma200") is None
    entry_plan = _build_entry_plan(
        ticker, price, trend, quality, indicators,
        qp.get("conditions") or {}, vb.get("conditions") or {},
        earnings_days, earnings_known, spy_gate, news, fundamentals,
    )
    if can_buy:
        action = passing["action"]
        invalidation = action.get("invalidation_price")
        stock = {
            "decision": "buy",
            "tier": "buy_now",
            "label": "BUY NOW",
            "reason": f"{passing.get('setup_name')} fired today, with a clear price where it is wrong.",
            "reasons": [f"{passing.get('setup_name')} fired today."] + supports[1:3],
            "what_would_change": (
                f"A close below ${invalidation} would change this."
                if invalidation is not None else
                "A close below the invalidation price would change this."
            ),
            "positive_note": "The rule fired today, with a clear price where it is wrong.",
            "price": _money(price),
            "passing_setup_key": passing.get("setup_key"),
            "passing_setup_name": passing.get("setup_name"),
            "entry_price": _money(action.get("entry_price")),
            "invalidation_price": _money(invalidation),
            "target_price": _money(action.get("target_price")),
            "exit_rule": action.get("exit_rule"),
            "entry_plan": None,
            "blocker": None,
        }
    elif trend_broken:
        avoid_reasons = []
        if trend.get("above_ma200") is False:
            avoid_reasons.append("Price is below its 200-day average.")
        if trend.get("ma200_direction") == "falling":
            avoid_reasons.append("The 200-day average is falling.")
        if trend.get("above_ma50") is False:
            avoid_reasons.append("Price is below its 50-day average.")
        if not avoid_reasons:
            avoid_reasons.append("The trend is broken, so no entry is offered.")
        stock = {
            "decision": "avoid",
            "tier": "avoid",
            "label": "AVOID",
            "reason": avoid_reasons[0],
            "reasons": avoid_reasons[:3],
            "what_would_change": (
                "A close back above the 200-day average, with that average "
                "rising again, plus a fresh pullback or breakout, would change this."
            ),
            "positive_note": "Avoiding a broken trend is also a decision, it is not a missed trade by default.",
            "price": _money(price),
            "passing_setup_key": None,
            "passing_setup_name": None,
            "entry_price": None,
            "invalidation_price": _money(trend.get("ma200")),
            "target_price": None,
            "exit_rule": None,
            "entry_plan": None,
            "blocker": None,
        }
    elif not earnings_known or spy_gate.get("spy_above_200") is None or trend_unknown:
        missing_reasons = []
        if not earnings_known:
            missing_reasons.append("We do not know the next earnings date, so no buy can be judged until it is known.")
        if spy_gate.get("spy_above_200") is None:
            missing_reasons.append("The wider market trend is unknown, so no buy can be judged until it is known.")
        if trend_unknown:
            missing_reasons.append("The trend averages are unavailable, so no buy can be judged until they are known.")
        stock = {
            "decision": "cannot_judge",
            "tier": "cannot_judge",
            "label": "CANNOT JUDGE",
            "reason": missing_reasons[0],
            "reasons": missing_reasons[:3],
            "what_would_change": _what_would_change(
                qp.get("conditions") or {}, vb.get("conditions") or {},
                earnings_days, spy_gate.get("spy_above_200"),
            ),
            "positive_note": "No verdict is better than a guessed one. The trend and trigger are shown below, but no buy is offered until the missing data is known.",
            "price": _money(price),
            "passing_setup_key": None,
            "passing_setup_name": None,
            "entry_price": None,
            "invalidation_price": None,
            "target_price": None,
            "exit_rule": None,
            "entry_plan": entry_plan,
            "blocker": entry_plan["blocker"],
        }
    else:
        reasons = []
        if not earnings_ok:
            reasons.append(f"Earnings are in {earnings_days} day(s), so BUY is blocked until after the report.")
        if spy_below:
            reasons.append("The wider market is below its 200-day average, so BUY is blocked.")
        suppressed_live = [
            s for s in setups
            if s.get("setup_key") in _LIVE_STOCK_SETUPS
            and s.get("rule_result") == "suppressed"
            and s.get("suppressed_reason")
        ]
        if suppressed_live:
            reasons.append(
                f"{suppressed_live[0].get('setup_name')} fired but was held back: "
                f"{suppressed_live[0].get('suppressed_reason')}."
            )
        if not reasons:
            reasons.append("No pullback to a rising average and no volume breakout today.")
        elif len(reasons) == 1 and not earnings_ok is False:
            reasons.append("No pullback to a rising average and no volume breakout today.")
        reasons = reasons[:3]
        stock = {
            "decision": "wait",
            "tier": "wait_for_entry",
            "label": "WAIT FOR ENTRY",
            "reason": reasons[0],
            "reasons": reasons,
            "what_would_change": entry_plan["what_flips_to_buy"],
            "positive_note": "Waiting for a trigger price is the entry plan, not indecision.",
            "price": _money(price),
            "passing_setup_key": None,
            "passing_setup_name": None,
            "entry_price": None,
            "invalidation_price": entry_plan["invalidation_price"],
            "target_price": None,
            "exit_rule": None,
            "entry_plan": entry_plan,
            "blocker": entry_plan["blocker"],
        }

    # Sell a put: on BUY NOW, as before, and on WAIT FOR ENTRY, as a
    # discount entry, but only with the same gates and a real cushion.
    # A WAIT put needs earnings known and more than 5 days away, SPY
    # above its 200-day, and a strike at least 4% below the price.
    # A BUY put keeps its original rule, with its cushion reported.
    # CANNOT JUDGE, AVOID, and any gate block offer no put at all.
    put_eligible = stock["decision"] in ("buy", "wait")
    if not put_eligible or not earnings_ok or not spy_ok:
        if stock["decision"] == "cannot_judge" and not earnings_known:
            put_reason, put_code = (
                "The next earnings date is unknown, so no put can be judged.",
                "earnings_unknown",
            )
        elif not earnings_ok:
            put_reason, put_code = (
                "Earnings block the stock verdict, so no put is offered.",
                "earnings_block",
            )
        elif not spy_ok:
            put_reason, put_code = (
                "The wider market gate blocks the stock verdict, so no put is offered.",
                "spy_block",
            )
        else:
            put_reason, put_code = (
                f"The stock verdict is {stock['label']}, so no put is offered.",
                "stock_not_buy_now",
            )
        put = {
            "decision": "not_available",
            "label": "NOT AVAILABLE",
            "reason": put_reason,
            "reason_code": put_code,
            "strike": None, "expiry": None, "dte": None,
            "premium_per_share": None, "premium_per_contract": None,
            "breakeven": None, "assignment_price": None,
            "max_loss_per_contract": None, "price_source": None,
            "why": None, "cushion_pct": None, "earnings_before_expiry": None,
        }
    else:
        row, fail = _select_put(price, chain_puts)
        if fail is not None:
            code, reason = fail
            put = {
                "decision": "dont_sell",
                "label": "DON'T SELL A PUT",
                "reason": reason,
                "reason_code": code,
                "strike": None, "expiry": None, "dte": None,
                "premium_per_share": None, "premium_per_contract": None,
                "breakeven": None, "assignment_price": None,
                "max_loss_per_contract": None, "price_source": None,
                "why": None, "cushion_pct": None, "earnings_before_expiry": None,
            }
        else:
            strike = _money(row.get("strike"))
            premium = _money(row.get("bid"))
            cushion = round((price - strike) / price * 100, 2) if price else None
            if stock["decision"] == "wait" and cushion is not None and cushion < 4.0:
                put = {
                    "decision": "dont_sell",
                    "label": "DON'T SELL A PUT",
                    "reason": (
                        f"The nearest ~0.30 delta put sits only {cushion}% below "
                        "the price, below the 4% cushion floor for a WAIT entry, "
                        "so no put is offered."
                    ),
                    "reason_code": "cushion_too_thin",
                    "strike": None, "expiry": None, "dte": None,
                    "premium_per_share": None, "premium_per_contract": None,
                    "breakeven": None, "assignment_price": None,
                    "max_loss_per_contract": None, "price_source": None,
                    "why": None, "cushion_pct": cushion, "earnings_before_expiry": None,
                }
            else:
                put_dte = row.get("dte")
                earnings_before = None
                if earnings_days is not None and put_dte is not None:
                    try:
                        earnings_before = bool(earnings_days <= float(put_dte))
                    except (TypeError, ValueError):
                        earnings_before = None
                put = {
                    "decision": "sell",
                    "label": "SELL THE PUT",
                    "reason": f"Sell the {row.get('expiry')} ${strike} put and collect ${round(premium * 100)} now.",
                    "reason_code": None,
                    "strike": strike,
                    "expiry": row.get("expiry"),
                    "dte": row.get("dte"),
                    "premium_per_share": premium,
                    "premium_per_contract": round(premium * 100, 2),
                    "breakeven": _money(strike - premium),
                    "assignment_price": strike,
                    "max_loss_per_contract": round((strike - premium) * 100, 2),
                    "price_source": "bid",
                    "why": (
                        f"You collect ${round(premium * 100)} now and buy the stock at "
                        f"${strike} if it falls there, lower than today's ${price}."
                    ),
                    "cushion_pct": cushion,
                    "earnings_before_expiry": earnings_before,
                }

    # Buy a call, only when the stock is BUY NOW. A WAIT stock needs
    # a move, not just quality, so no call is offered on WAIT.
    if stock["decision"] != "buy":
        call = {
            "decision": "not_available",
            "label": "NOT AVAILABLE",
            "reason": f"The stock verdict is {stock['label']}, not BUY NOW, so no call is offered.",
            "reason_code": "stock_not_buy_now",
            "strike": None, "expiry": None, "dte": None,
            "premium_per_share": None, "premium_per_contract": None,
            "breakeven": None, "max_loss_per_contract": None,
            "invalidation_price": None, "premium_source": None,
            "why": None,
        }
    else:
        row, fail = _select_call(price, chain_calls)
        if fail is not None:
            code, reason = fail
            call = {
                "decision": "dont_buy",
                "label": "DON'T BUY THE CALL",
                "reason": reason,
                "reason_code": code,
                "strike": None, "expiry": None, "dte": None,
                "premium_per_share": None, "premium_per_contract": None,
                "breakeven": None, "max_loss_per_contract": None,
                "invalidation_price": None, "premium_source": None,
                "why": None,
            }
        else:
            strike = _money(row.get("strike"))
            ask = row.get("ask")
            mid = row.get("mid")
            try:
                ask = float(ask) if ask is not None else None
            except (TypeError, ValueError):
                ask = None
            try:
                mid = float(mid) if mid is not None else None
            except (TypeError, ValueError):
                mid = None
            if ask is not None and ask > 0:
                premium, premium_source = _money(ask), "ask"
            else:
                premium, premium_source = _money(mid), "mid"
            call = {
                "decision": "buy",
                "label": "BUY THE CALL",
                "reason": f"Buy the {row.get('expiry')} ${strike} call for ${round(premium * 100)}.",
                "reason_code": None,
                "strike": strike,
                "expiry": row.get("expiry"),
                "dte": row.get("dte"),
                "premium_per_share": premium,
                "premium_per_contract": round(premium * 100, 2),
                "breakeven": _money(strike + premium),
                "max_loss_per_contract": round(premium * 100, 2),
                "invalidation_price": stock["invalidation_price"],
                "premium_source": premium_source,
                "why": (
                    f"If the stock rises above ${round(strike + premium, 2)}, the call "
                    f"pays off. The most you can lose is the ${round(premium * 100)} paid."
                ),
            }

    # Long-term lane: computed after timing, never used by put or
    # call gating above. When the lane says "Long-term buy
    # candidate, wait for entry", the entry prices come from the
    # WAIT entry plan computed above, even when the timing verdict
    # itself is AVOID and therefore carries no entry plan of its own.
    if longterm is None:
        try:
            from services.longterm_valuation import build_longterm

            longterm = build_longterm(
                ticker, price,
                _fundamentals_for(ticker, fundamentals),
                statements=longterm_statements,
                risk_free_rate=longterm_risk_free_rate,
                erp=longterm_erp,
            )
        except Exception as exc:
            logger.warning(
                "ticker_lookup: long-term lane failed for %s: %s",
                ticker, exc,
            )
            longterm = {
                "verdict": "blocked",
                "label": "BLOCKED",
                "reason": "The long-term lane could not be computed.",
                "reason_code": "longterm_error",
                "quality": {"status": "not_verified"},
                "dcf": None, "wacc": None,
                "bridge_line": None, "bridge_entry": None,
                "notes": ["Long-term lane error, timing verdict unaffected."],
            }
    if isinstance(longterm, dict) and longterm.get("bridge_line") \
            and not longterm.get("bridge_entry"):
        longterm = dict(longterm)
        longterm["bridge_entry"] = {
            "pullback_price": entry_plan.get("pullback_price"),
            "breakout_price": entry_plan.get("breakout_price"),
            "buy_zone": entry_plan.get("buy_zone"),
            "invalidation_price": entry_plan.get("invalidation_price"),
            "what_flips_to_buy": entry_plan.get("what_flips_to_buy"),
            "blocker": entry_plan.get("blocker"),
        }

    return {
        "stock": stock,
        "put": put,
        "call": call,
        "longterm": longterm,
        "conviction": {
            "supports": supports,
            "against": against,
            "missing": missing,
        },
        "news": news,
        "earnings": {
            "anticipated_date": earnings.get("earnings_date"),
            "days_away": earnings_days,
            "status": earnings.get("status"),
            "consensus_estimate_eps": None,
            "estimate_source": None,
            "reported_eps": None,
            "reported_vs_estimate": None,
            "beat_or_miss": None,
            "note": (
                "Anticipated: the next earnings date from the Finnhub "
                "earnings calendar. Actual: not available, the app has "
                "no reliable consensus-estimate or beat-or-miss feed, "
                "so no beat or miss is guessed."
            ),
        },
    }


def _evaluate_setups(ticker: str, inputs: LookupInputs, db,
                     registry_statuses: Optional[dict],
                     signal_date: Optional[date]) -> list:
    """Run the alert-engine evaluators for one ticker, read-only.

    One setup failing on live data must not kill the whole snapshot:
    the scheduled engine wraps each ticker the same way, so the lookup
    wraps each evaluator and each action build, and reports the setup
    as failed with a named evaluator_error reason instead of raising.
    """
    import services.alert_engine as ae

    statuses = registry_statuses if registry_statuses is not None else _registry_statuses(db)
    ind = inputs.indicators
    results = []
    for setup_key, (evaluator_fn, _job) in ae._SETUP_EVALUATORS.items():
        status = statuses.get(setup_key, "unknown")
        name = _SETUP_NAMES.get(setup_key, setup_key)
        rule_key = f"alert.{setup_key}"
        if status == "RETIRED":
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "not_evaluated", "fires": False,
                "conditions": {}, "action": None,
                "suppressed_reason": "retired_no_reliable_feed",
            })
            continue
        if status == "not_registered":
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "not_evaluated", "fires": False,
                "conditions": {}, "action": None,
                "suppressed_reason": "rule_not_registered",
            })
            continue
        try:
            if setup_key == "premium_at_support":
                fires, cond = evaluator_fn(ind, inputs.earnings_days, inputs.iv_percentile)
            elif setup_key in ("quality_pullback", "volume_breakout"):
                fires, cond = evaluator_fn(
                    ind, inputs.earnings_days,
                    spy_gate=inputs.spy_gate, spy_vs_200ma_pct=inputs.spy_vs_200ma_pct,
                )
            else:
                fires, cond = evaluator_fn(ind, inputs.earnings_days)
        except Exception as e:
            logger.warning(
                "ticker_lookup: evaluator %s failed for %s: %s",
                setup_key, ticker, e,
            )
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "fail", "fires": False,
                "conditions": {}, "action": None,
                "suppressed_reason": f"evaluator_error:{type(e).__name__}",
            })
            continue
        if not fires:
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "fail", "fires": False,
                "conditions": cond, "action": None,
                "suppressed_reason": None,
            })
            continue
        # Same action builder as the live run, so the numbers match.
        try:
            alert = ae._build_alert(
                setup_key, name, status, ticker, ind, cond, db,
                signal_date=signal_date,
            )
        except Exception as e:
            logger.warning(
                "ticker_lookup: action build %s failed for %s: %s",
                setup_key, ticker, e,
            )
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "suppressed", "fires": True,
                "conditions": cond, "action": None,
                "suppressed_reason": f"evaluator_error:{type(e).__name__}",
            })
            continue
        if alert.get("is_suppressed"):
            results.append({
                "setup_key": setup_key, "rule_key": rule_key,
                "setup_name": name, "status": status,
                "rule_result": "suppressed", "fires": True,
                "conditions": cond, "action": None,
                "suppressed_reason": alert.get("suppressed_reason"),
            })
            continue
        action = {
            "action": alert.get("action"),
            "entry_price": alert.get("entry_price"),
            "entry_source": alert.get("entry_source"),
            "invalidation_price": alert.get("invalidation_price"),
            "target_price": alert.get("target_price"),
            "exit_rule": alert.get("exit_rule"),
            "expiry": alert.get("expiry"),
            "strike": alert.get("strike"),
            "premium": alert.get("premium"),
            "max_loss": alert.get("max_loss"),
            "max_loss_per_contract": alert.get("max_loss_per_contract"),
            "position_size_shares": alert.get("position_size_shares"),
            "position_size_contracts": alert.get("position_size_contracts"),
            "risk_dollars": alert.get("risk_dollars"),
            "risk_pct_actual": alert.get("risk_pct_actual"),
            "sizing_source": alert.get("sizing_source"),
            "sizing_note": alert.get("sizing_note"),
            "account_equity": alert.get("account_equity"),
            "equity_source": alert.get("equity_source"),
            "action_summary": alert.get("action_summary"),
            "invalidation_text": alert.get("invalidation_text"),
            "reason": alert.get("reason"),
        }
        results.append({
            "setup_key": setup_key, "rule_key": rule_key,
            "setup_name": name, "status": status,
            "rule_result": "pass", "fires": True,
            "conditions": cond, "action": action,
            "suppressed_reason": None,
        })
    for setup_key, (status, reason, note) in _NOT_EVALUATED.items():
        results.append({
            "setup_key": setup_key,
            "rule_key": f"alert.{setup_key}",
            "setup_name": _SETUP_NAMES.get(setup_key, setup_key),
            "status": status, "rule_result": "not_evaluated",
            "fires": False, "conditions": {},
            "action": None, "suppressed_reason": reason,
            "note": note,
        })
    return results


class LiveLookupProvider:
    """Fetches LookupInputs from the same sources as the alert engine."""

    def __init__(self, db=None):
        self.db = db

    def fetch(self, ticker: str) -> LookupInputs:
        import services.alert_engine as ae

        df = ae._fetch_ohlcv(ticker)
        if df is None:
            raise LookupError(
                "no_data",
                f"no_data: no price history found for {ticker}",
            )
        ind = ae._indicators(df)
        if ind is None:
            raise LookupError(
                "no_indicators",
                f"no_indicators: fewer than 210 bars for {ticker}, "
                "not enough history to compute the setup indicators",
            )
        try:
            last = df.index[-1]
            data_timestamp = last.date().isoformat() if hasattr(last, "date") else str(last)
        except Exception:
            data_timestamp = None
        earnings_days = ae._earnings_days(ticker)
        earnings_date = None
        if earnings_days is not None:
            earnings_date = (date.today() + timedelta(days=earnings_days)).isoformat()
        iv_pct = ae._iv_percentile(self.db, ticker)
        spy_gate, spy_detail = ae._spy_gate()
        chain_puts, chain_calls, chain_source, chain_error = self._fetch_chain(
            ticker, ind["price"]
        )
        news_items, news_source, news_error = self._fetch_news(ticker)
        return LookupInputs(
            indicators=ind,
            data_timestamp=data_timestamp,
            price_source="yfinance_ohlcv",
            earnings_days=earnings_days,
            earnings_date=earnings_date,
            iv_percentile=iv_pct,
            iv_source="iv_store" if iv_pct is not None else "unavailable",
            spy_gate=spy_gate,
            spy_vs_200ma_pct=spy_detail.get("spy_vs_200ma_pct"),
            chain_puts=chain_puts,
            chain_calls=chain_calls,
            chain_source=chain_source,
            chain_error=chain_error,
            chain_fetched_at=datetime.now(timezone.utc).isoformat(),
            news_items=news_items,
            news_source=news_source,
            news_error=news_error,
        )

    @staticmethod
    def _fetch_news(ticker: str):
        """Recent articles from Polygon ticker news.

        Returns (items, source, error). A failure is reported, not
        guessed: the verdict records news as unavailable. Titles
        without a date are kept here and marked unverifiable by
        _news_verdict, which is the only place news is judged.
        """
        try:
            from services.polygon_client import get_news

            items = get_news(ticker, limit=5) or []
            return items, "polygon_news", None
        except Exception as e:
            logger.debug("ticker_lookup: Polygon news failed for %s: %s", ticker, e)
            return [], "polygon_news", f"news_unavailable: {type(e).__name__}"

    @staticmethod
    def _fetch_chain(ticker: str, price: float):
        """Listed chain, nearest 21 DTE, 5 nearest strikes per side.

        Returns (puts, calls, source, error). A total chain failure is
        reported, not guessed: the snapshot still returns, with the
        options result suppressed as no_listed_chain.
        """
        from services.chain_provider import ChainProvider

        provider = ChainProvider()
        puts, calls = [], []
        sources, errors = [], []
        for contract_type in ("put", "call"):
            result = provider.fetch(ticker, contract_type, 14, 28, near_price=price)
            if hasattr(result, "rows"):
                rows = sorted(result.rows, key=lambda r: abs(r["strike"] - price))[:5]
                rows = sorted(rows, key=lambda r: r["strike"])
                if contract_type == "put":
                    puts = rows
                else:
                    calls = rows
                sources.append(result.source)
            else:
                errors.append(getattr(result, "reason", "no chain data"))
        source = sources[0] if sources else None
        error = None if (puts or calls) else ("no_listed_chain: " + "; ".join(errors) if errors else "no_listed_chain")
        return puts, calls, source, error


def evaluate_lookup(ticker: str, *, inputs: Optional[LookupInputs] = None,
                    provider=None, db=None,
                    registry_statuses: Optional[dict] = None,
                    explain_fn=None,
                    signal_date: Optional[date] = None,
                    longterm_statements: Optional[dict] = None,
                    longterm_risk_free_rate: Optional[float] = None,
                    longterm_erp: Optional[float] = None) -> dict:
    """Pure, deterministic lookup for one ticker.

    Same inputs give the same result. No DB writes, no alerts, no
    notifications. explain_fn, when given, is called through
    ai_boundary.explain_or_fallback and can only supply the
    plain-language explanation; a failure leaves the quant result
    untouched and the quant fallback text is used.
    """
    from services.ai_boundary import explain_or_fallback, quant_fallback_explanation

    ticker = normalize_ticker(ticker)
    if inputs is None:
        inputs = (provider or LiveLookupProvider(db)).fetch(ticker)
    ind = inputs.indicators
    if ind is None or ind.get("price") is None:
        raise LookupError("no_data", f"no_data: no price found for {ticker}")
    price = ind["price"]
    quality = _quality_score(ind, inputs.iv_percentile)
    earnings_known = inputs.earnings_days is not None
    setups = _evaluate_setups(ticker, inputs, db, registry_statuses, signal_date)
    trend = _trend(ind)
    earnings = {
        "status": "known" if earnings_known else "earnings_unknown",
        "earnings_days": inputs.earnings_days,
        "earnings_date": inputs.earnings_date,
        "source": "finnhub_earnings_calendar",
        "note": (
            None if earnings_known else
            "earnings_unknown: no earnings date on the calendar, "
            "so every setup is fail-closed"
        ),
    }
    news = _news_verdict(
        inputs.news_items, inputs.news_source, inputs.news_error,
        signal_date or date.today(),
    )
    verdict = build_verdict(
        ticker, price=price, setups=setups,
        earnings=earnings,
        spy_gate={
            "spy_above_200": inputs.spy_gate,
            "spy_vs_200ma_pct": inputs.spy_vs_200ma_pct,
            "gate": (
                "pass" if inputs.spy_gate is True
                else "block_below_200" if inputs.spy_gate is False
                else "block_unknown"
            ),
        },
        quality=quality, trend=trend,
        iv_percentile=inputs.iv_percentile, news=news,
        chain_puts=inputs.chain_puts, chain_calls=inputs.chain_calls,
        as_of=signal_date or date.today(),
        indicators=ind,
        longterm_statements=longterm_statements,
        longterm_risk_free_rate=longterm_risk_free_rate,
        longterm_erp=longterm_erp,
    )
    chain_available = bool(inputs.chain_puts or inputs.chain_calls)
    if not chain_available and inputs.chain_error is None:
        chain_error = "no_listed_chain"
    else:
        chain_error = inputs.chain_error
    fallback_text = quant_fallback_explanation(
        ticker, quality["composite"], "ticker_lookup",
        f"Price ${price:.2f} at {inputs.data_timestamp or 'unknown date'}.",
    )
    explanation = fallback_text
    explanation_source = "quant_fallback"
    if explain_fn is not None:
        explanations = explain_or_fallback(
            explain_fn,
            [{"ticker": ticker, "quant_score": quality["composite"],
              "strategy": "ticker_lookup"}],
            fallback_text,
        )
        explanation = explanations.get(ticker, fallback_text)
        explanation_source = "claude" if explanation != fallback_text else "quant_fallback"
    # Sanitized so the response always JSON-encodes: live evaluator
    # output can carry numpy scalars or NaN, which 500 the lookup at
    # response encoding even though the lookup itself succeeded.
    return _json_safe({
        "ticker": ticker,
        "lookup_type": "query",
        "is_recommendation": False,
        "disclaimer": (
            "Rule result for this ticker at the data timestamp shown. "
            "Not a trade recommendation. No alert was fired, no journal "
            "row was created, and no notification was sent."
        ),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "data_timestamp": inputs.data_timestamp,
        "price": round(price, 2),
        "price_source": inputs.price_source,
        "trend": trend,
        "quality": quality,
        "earnings": earnings,
        "news": {
            "status": news["status"],
            "source": news["source"],
            "error": news["error"],
            "latest": news["latest"],
            "fresh_company_release": news["fresh_company_release"],
            "note": news["note"],
        },
        "verdict": verdict,
        "iv": {
            "iv_percentile": inputs.iv_percentile,
            "source": inputs.iv_source,
            "note": None if inputs.iv_percentile is not None else "IV unavailable",
        },
        "spy_gate": {
            "spy_above_200": inputs.spy_gate,
            "spy_vs_200ma_pct": inputs.spy_vs_200ma_pct,
            "gate": (
                "pass" if inputs.spy_gate is True
                else "block_below_200" if inputs.spy_gate is False
                else "block_unknown"
            ),
        },
        "setups": setups,
        "chain": {
            "available": chain_available,
            "source": inputs.chain_source,
            "fetched_at": inputs.chain_fetched_at,
            "error": chain_error,
            "puts": inputs.chain_puts,
            "calls": inputs.chain_calls,
        },
        "explanation": explanation,
        "explanation_source": explanation_source,
    })


# ---------------------------------------------------------------------------
# Brief in-memory cache (lookup_ticker only, never evaluate_lookup)
# ---------------------------------------------------------------------------

_CACHE: dict = {}


def clear_lookup_cache() -> None:
    _CACHE.clear()


def lookup_ticker(ticker: str, db=None, explain_fn=None,
                  signal_date: Optional[date] = None) -> dict:
    """Cached lookup for the live path. Same ticker within the TTL
    returns the stored quant result, labelled cached, with its original
    data timestamp. Never served past the TTL."""
    ticker = normalize_ticker(ticker)
    now = time.monotonic()
    entry = _CACHE.get(ticker)
    if entry is not None:
        result, stored_at = entry
        if now - stored_at < LOOKUP_CACHE_TTL_SECONDS:
            cached = copy.deepcopy(result)
            cached["cached"] = True
            cached["fetched_at"] = datetime.now(timezone.utc).isoformat()
            return _attach_explanation(cached, ticker, explain_fn)
        del _CACHE[ticker]
    result = evaluate_lookup(ticker, db=db, signal_date=signal_date)
    _CACHE[ticker] = (copy.deepcopy(result), now)
    fresh = copy.deepcopy(result)
    return _attach_explanation(fresh, ticker, explain_fn)


def _attach_explanation(result: dict, ticker: str, explain_fn) -> dict:
    """Attach a Claude explanation to an already-computed quant result.

    A Claude failure never changes the quant result: the quant
    fallback text stays in place.
    """
    from services.ai_boundary import explain_or_fallback, quant_fallback_explanation

    if explain_fn is None:
        return result
    quality = result.get("quality") or {}
    fallback_text = quant_fallback_explanation(
        ticker, quality.get("composite"), "ticker_lookup",
        f"Price ${result.get('price')} at {result.get('data_timestamp') or 'unknown date'}.",
    )
    explanations = explain_or_fallback(
        explain_fn,
        [{"ticker": ticker, "quant_score": quality.get("composite"),
          "strategy": "ticker_lookup"}],
        fallback_text,
    )
    explanation = explanations.get(ticker, fallback_text)
    result["explanation"] = explanation
    result["explanation_source"] = "claude" if explanation != fallback_text else "quant_fallback"
    return result
