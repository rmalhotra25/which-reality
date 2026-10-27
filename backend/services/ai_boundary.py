"""AI boundary: quant decides, Claude explains.

One place that states the rule for the whole live path, so no engine
has to restate it and no engine can quietly reintroduce a Claude
decision:

- Entry, stop, target or exit rule, strike, size, rank, score, and
  grade come only from deterministic quant rules and the listed
  option chain. No Claude value may override, average into, or
  replace a quant value in the live path.
- Claude may write plain-language explanations only: why now, the
  thesis, what would change the mind, and grading commentary on
  settled trades. Its output is labelled as explanation, never as
  a decision.
- If Claude and the chain or quant disagree, the chain and quant
  win and the Claude value is dropped, and the drop is logged, not
  silently averaged.
- A missing or failed Claude call must not change, delay, or
  suppress the quant decision. The alert still fires with the full
  quant instruction, with a quant-derived explanation in place of
  the missing Claude text.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Decision fields a language model must never set in the live path.
# Any value Claude returns for one of these is dropped, not shown.
AI_DECISION_FIELDS = frozenset({
    "rank",
    "score",
    "combined_score",
    "qual_score",
    "strike",
    "put_strike",
    "entry_price",
    "exit_price",
    "stop_loss",
    "underlying_entry",
    "underlying_target",
    "underlying_stop",
    "short_call_strike",
    "long_call_strike",
    "short_put_strike",
    "long_put_strike",
    "net_credit",
    "max_profit",
    "max_loss",
    "breakeven_low",
    "breakeven_high",
    "put_premium",
    "assignment_chance_pct",
    "assignment_risk",
    "long_term_rec",
    "dcf_params",
    "buy_zone_low",
    "buy_zone_high",
    "invalidation_stop",
    "target_price",
    "call_strike",
    "call_expiry",
})


def valid_expiry_dates(n: int = 6) -> list[str]:
    """Return the next n upcoming Friday dates at least 5 days away.

    These are real tradeable weekly/monthly expiries. Pure date math,
    no model involved, so the live path can use it without Claude.
    """
    today = datetime.now(timezone.utc).date()
    days_to_friday = (4 - today.weekday()) % 7  # weekday 4 = Friday
    if days_to_friday < 5:
        days_to_friday += 7
    fridays = []
    d = today + timedelta(days=days_to_friday)
    for _ in range(n):
        fridays.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return fridays


def grade_from_quant_score(score: float | None) -> str:
    """Deterministic grade from a quant composite score, same bands as the old rubric."""
    if score is None:
        return "C"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def assignment_risk_from_chance(chance_pct: float | None) -> str:
    """Assignment risk band from a delta-derived assignment chance."""
    if chance_pct is None:
        return "UNKNOWN"
    if chance_pct < 25:
        return "LOW"
    if chance_pct <= 40:
        return "MODERATE"
    return "HIGH"


def rank_quant_candidates(quant_scores: dict) -> list[str]:
    """Rank tickers by quant composite, highest first.

    Ties break on ticker alphabetically, so the same inputs always
    give the same order. No model, no shuffle, no time-of-day input.
    """
    def _key(item):
        ticker, qs = item
        composite = (qs or {}).get("composite")
        try:
            value = float(composite)
        except (TypeError, ValueError):
            value = float("-inf")
        return (-value, ticker)

    return [ticker for ticker, _ in sorted(quant_scores.items(), key=_key)]


def drop_ai_decision(ticker: str, field: str, ai_value, quant_value) -> None:
    """Log a dropped Claude decision value. The quant value stands."""
    logger.warning(
        "AI boundary: dropped Claude %s for %s (Claude=%r, quant=%r, quant wins)",
        field, ticker, ai_value, quant_value,
    )


def explain_or_fallback(explain_fn, candidates: list[dict], fallback_text: str) -> dict[str, str]:
    """Run a Claude explainer, never letting it change the decision.

    Returns {ticker: explanation}. On any failure, or for any ticker
    Claude did not explain, the caller-supplied quant-derived text is
    used. The function never raises, so a Claude outage cannot delay
    or suppress the quant decision that already happened.
    """
    explanations: dict[str, str] = {}
    try:
        result = explain_fn(candidates)
    except Exception as e:
        logger.warning("AI boundary: Claude explanation failed, using quant fallback: %s", e)
        result = None
    if isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker", "")).upper()
            text = str(item.get("explanation", "") or "").strip()
            if ticker and text:
                explanations[ticker] = text
    for cand in candidates:
        ticker = str(cand.get("ticker", "")).upper()
        if ticker and ticker not in explanations:
            explanations[ticker] = fallback_text
    return explanations


def quant_fallback_explanation(ticker: str, quant_score: float | None,
                               strategy: str, detail: str = "") -> str:
    """Quant-derived explanation text, used when Claude is unavailable.

    States only what the quant rule computed, so the card is never
    empty and never invents a thesis.
    """
    score = f"{quant_score:.1f}" if quant_score is not None else "n/a"
    text = f"Quant score {score}, strategy {strategy}."
    if detail:
        text = f"{text} {detail}"
    return text


def assert_no_ai_decisions(records: list[dict], source: str) -> None:
    """Test helper: raise if any record carries a Claude decision field.

    Live-path records carry quant values under the decision field
    names, so this is used by tests with the Claude payload kept
    separate: pass the Claude payloads, not the stored records.
    """
    for rec in records or []:
        for field in AI_DECISION_FIELDS:
            if field in rec and rec.get("_decision_source") == "claude":
                raise AssertionError(f"{source}: Claude decision field present: {field}")
