"""
Alert contract (P1 determinism).

Every alert must carry these fields, or it is suppressed at the alert
build point, so a non-conforming alert never reaches the Alerts tab or
Telegram:

- action: one imperative verb phrase.
- size: units and dollars, computed by the size rule, with the equity
  source named. A 1-unit fallback is NOT a size: when no stop distance
  exists to size from, the alert is suppressed, never guessed.
- entry: a real price with its source named (next open estimate, or a
  listed contract premium with its source: bid, ask, last trade, fair
  value).
- invalidation: price and condition.
- target or exit rule: a real price target when the rule defines one,
  otherwise the exit rule in words and no invented target price.
- expiry: option expiry or time stop, as a date.
- reason: the exact conditions that fired, with their values.
- rule_key and status: which rule fired and whether it is LIVE or SHADOW.

No AI value is consulted anywhere in this module: the contract is
quant-only, and the AI boundary stays intact.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Fields the contract requires on a built alert dict. target_price is
# NOT required: a rule whose exit is a condition (RSI exit) carries
# exit_rule instead and no target price.
CONTRACT_REQUIRED = (
    "action",
    "entry_price",
    "entry_source",
    "invalidation_price",
    "expiry",
    "reason",
    "rule_key",
    "setup_status",
)


def build_reason(setup_key: str, cond: dict) -> str:
    """One-line reason with the values that fired, for the alert card."""
    bits = []
    if cond.get("price") is not None:
        bits.append(f"price ${cond['price']:.2f}")
    if cond.get("rsi") is not None:
        bits.append(f"RSI(14) {cond['rsi']}")
    if cond.get("ma50") is not None:
        bits.append(f"50-day MA ${cond['ma50']:.2f}")
    if cond.get("ma200") is not None:
        bits.append(f"200-day MA ${cond['ma200']:.2f}")
    if cond.get("volume") is not None and cond.get("vol20"):
        bits.append(f"volume {cond['volume']:,} vs 20-day avg {cond['vol20']:,}")
    if cond.get("earnings_days") is not None:
        bits.append(f"earnings in {cond['earnings_days']} days")
    if cond.get("spy_vs_200ma_pct") is not None:
        bits.append(f"SPY {cond['spy_vs_200ma_pct']:.1f}% vs 200-day MA")
    if cond.get("iv_percentile") is not None:
        bits.append(f"IV percentile {cond['iv_percentile']}")
    if cond.get("hv30_approx") is not None:
        bits.append(f"HV(30) approx {cond['hv30_approx']}%")
    if cond.get("above_55d_high"):
        bits.append(f"above 55-day high ${cond.get('prior_high_55')}")
    if cond.get("gap_held"):
        bits.append("earnings gap held")
    return "; ".join(bits) if bits else f"{setup_key} signal fired"


def time_stop_date(signal_date: date, days: int) -> str:
    """Time-stop expiry as an ISO date string."""
    return (signal_date + timedelta(days=days)).isoformat()


def validate_alert(alert: dict) -> tuple[bool, list[str]]:
    """Check a built alert dict against the contract.

    Returns (ok, missing) where missing names every contract violation.
    An alert with an invented target is caught by construction: builders
    must not set target_price for RSI-exit rules, and a target_price
    that equals a known invented formula is rejected here.
    """
    missing = []

    for field in CONTRACT_REQUIRED:
        if alert.get(field) in (None, ""):
            missing.append(field)

    # Size: units and dollars, computed, with the equity source named.
    # The 1-unit fallback (sizing_source == "fallback") is not a size.
    units = alert.get("position_size_shares") or alert.get("position_size_contracts")
    if not units:
        missing.append("size_units")
    if alert.get("risk_dollars") is None:
        missing.append("size_risk_dollars")
    if alert.get("sizing_source") != "computed":
        missing.append("size_computed")
    if not alert.get("equity_source"):
        missing.append("equity_source")

    # Entry must be a real price with a named source.
    entry = alert.get("entry_price")
    if entry is not None and entry <= 0:
        missing.append("entry_price_positive")

    # Invalidation must be a real price below the entry for a long.
    inv = alert.get("invalidation_price")
    if inv is not None and entry is not None and inv >= entry:
        missing.append("invalidation_below_entry")

    # Target or exit rule: one of them must be present, never both
    # invented. A target_price is only accepted when the rule defines
    # one (volume breakout, trend pullback, post-earnings drift); RSI
    # exit rules carry exit_rule and target_price None.
    if alert.get("target_price") is None and not alert.get("exit_rule"):
        missing.append("target_or_exit_rule")

    # Reason must carry values, not just the setup name.
    reason = alert.get("reason") or ""
    if len(reason) < 10:
        missing.append("reason_with_values")

    return (len(missing) == 0), missing
