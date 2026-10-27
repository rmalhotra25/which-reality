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
        )

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
                    signal_date: Optional[date] = None) -> dict:
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
        "trend": _trend(ind),
        "quality": quality,
        "earnings": {
            "status": "known" if earnings_known else "earnings_unknown",
            "earnings_days": inputs.earnings_days,
            "earnings_date": inputs.earnings_date,
            "source": "finnhub_earnings_calendar",
            "note": (
                None if earnings_known else
                "earnings_unknown: no earnings date on the calendar, "
                "so every setup is fail-closed"
            ),
        },
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
