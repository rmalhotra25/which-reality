"""
Down-market put strategy for Directional (setup_id: directional_puts).

Two variants, both priced from the real listed chain at the stated 21
days to expiry, using the same Directional math as calls: real
P(profit) from the contract's own IV, one reward/risk figure, dollar
EV, earnings exclusion. The setup starts SHADOW until its backtest
passes on real data (see backtests/directional_puts.md).

Mechanical entry rules (stated in code and on the card):
- Trend: the stock must be below both its 50-day and its 200-day
  moving average. A put bought while the stock is above either average
  is a bet against the trend and is excluded.
- DTE: 21 days, snapped to the nearest listed expiry at or after 21
  days. Delta target 0.30 (absolute), accepted band 0.15 to 0.50.
- IV discipline: puts are expensive after volatility spikes, so do not
  chase an outright put when IV is rich. Outright long puts need the
  IV percentile below 75. At or above 75, or when the IV percentile
  is unknown, only the defined-risk bear spread variant is allowed:
  buy a higher-strike put, sell a lower-strike put, capped loss is
  the net debit, capped gain is the strike width minus the net debit.
- EV: expected value per contract must be above zero, otherwise the
  candidate is excluded.
- Earnings inside the expiry window excludes the candidate (IV crush).
- Max loss must fit the Challenge per-trade cap for the fit check.

Plain-language card copy is produced by put_plain_copy: every line
says what the trade means for the person's money, with no unexplained
jargon.
"""
import math

from services.directional_ranker import (
    compute_expected_value,
    compute_fits_challenge,
    compute_prob_profit,
    compute_reward_risk,
)

PUT_IV_PERCENTILE_MAX = 75.0
PUT_DELTA_TARGET = 0.30
PUT_DELTA_MIN = 0.15
PUT_DELTA_MAX = 0.50
PUT_DTE_TARGET = 21
PUT_EV_FLOOR = 0.0


def put_trend_confirmed(above_ma50, above_ma200) -> bool:
    """True only when the stock is below both its 50-day and 200-day averages.

    An unknown average is not a confirmation: it fails the trend rule.
    """
    return above_ma50 is False and above_ma200 is False


def iv_route(iv_percentile, iv_available: bool) -> tuple[str, str]:
    """Decide the allowed variant from the IV percentile.

    Returns ("outright", reason) when IV is cheap enough to buy a put
    outright, or ("spread", reason) when IV is rich or unknown and only
    the defined-risk bear spread is allowed.
    """
    if not iv_available or iv_percentile is None:
        return (
            "spread",
            "IV percentile unknown, so an outright put is blocked; "
            "only a bear spread (capped loss) is allowed",
        )
    if iv_percentile < PUT_IV_PERCENTILE_MAX:
        return (
            "outright",
            f"IV percentile {iv_percentile}% is below the {PUT_IV_PERCENTILE_MAX:.0f}% "
            "limit, so an outright put is allowed",
        )
    return (
        "spread",
        f"IV percentile {iv_percentile}% is at or above the {PUT_IV_PERCENTILE_MAX:.0f}% "
        "limit, so an outright put is blocked; only a bear spread "
        "(capped loss) is allowed",
    )


def bear_spread_payoffs(long_strike: float, short_strike: float,
                        long_premium: float, short_premium: float) -> dict:
    """Capped payoffs for a bear put spread, per contract.

    Buy the higher-strike put, sell the lower-strike put.
    Net debit is what you pay. Max loss is the net debit (both puts
    expire worthless). Max gain is the strike width minus the net
    debit (stock finishes below the short strike). Breakeven is the
    long strike minus the net debit.
    """
    net_debit = round(long_premium - short_premium, 2)
    width = round(long_strike - short_strike, 2)
    return {
        "net_debit": net_debit,
        "width": width,
        "max_loss": round(net_debit * 100, 2),
        "max_gain": round((width - net_debit) * 100, 2),
        "breakeven": round(long_strike - net_debit, 2),
    }


def bear_spread_payoff_at_target(long_strike: float, short_strike: float,
                                 net_debit: float, target: float) -> float:
    """Net payoff per contract if the stock finishes at the target."""
    long_intrinsic = max(long_strike - target, 0.0)
    short_intrinsic = max(short_strike - target, 0.0)
    return round((long_intrinsic - short_intrinsic - net_debit) * 100, 2)


def choose_bear_spread_short_leg(contracts: list, long_expiry: str,
                                 long_strike: float, price: float) -> dict | None:
    """Pick the short leg of a bear spread from listed contracts.

    Same expiry as the long leg, strike below the long strike, nearest
    to the long strike minus a width target of 5% of the stock price
    (at least $5). Returns the contract dict, or None when no listed
    strike qualifies.
    """
    width_target = max(5.0, round(price * 0.05, 2))
    wanted = long_strike - width_target
    best = None
    best_key = None
    for c in contracts or []:
        if str(c.get("expiry")) != str(long_expiry):
            continue
        strike = float(c.get("strike") or 0)
        if strike <= 0 or strike >= long_strike:
            continue
        key = abs(strike - wanted)
        if best_key is None or key < best_key:
            best_key = key
            best = c
    return best


def evaluate_put_candidate(
    prob_profit, payoff_at_target, payoff_at_stop, max_loss_per_contract,
    iv_percentile, iv_available: bool, above_ma50, above_ma200,
    earnings_in_window, delta_abs, per_trade_cap_dollars=None,
) -> dict:
    """Apply the put strategy rules to one candidate.

    Returns a dict with decision "outright", "spread", or "excluded",
    the reasons, EV, reward/risk, and the Challenge fit check. EV is
    computed with the same real-expectancy math as calls.
    """
    reasons: list[str] = []
    ev_dollars, ev_per_dollar = compute_expected_value(
        prob_profit, payoff_at_target, max_loss_per_contract
    )
    reward_risk = compute_reward_risk(payoff_at_target, payoff_at_stop)

    if earnings_in_window is True:
        reasons.append("earnings inside the expiry window, excluded (IV crush risk)")
    if not put_trend_confirmed(above_ma50, above_ma200):
        reasons.append(
            "trend rule failed: the stock must be below both its 50-day "
            "and 200-day averages for a put"
        )
    if delta_abs is not None and not (PUT_DELTA_MIN <= delta_abs <= PUT_DELTA_MAX):
        reasons.append(
            f"put delta {delta_abs:.2f} is outside the accepted band "
            f"{PUT_DELTA_MIN:.2f} to {PUT_DELTA_MAX:.2f} (target {PUT_DELTA_TARGET:.2f})"
        )
    if reasons:
        return {
            "decision": "excluded",
            "reasons": reasons,
            "ev_dollars": ev_dollars,
            "ev_per_dollar_risked": ev_per_dollar,
            "reward_risk": reward_risk,
            "fits_challenge": compute_fits_challenge(max_loss_per_contract, per_trade_cap_dollars),
            "put_variant": None,
        }

    route, route_reason = iv_route(iv_percentile, iv_available)
    # The EV floor applies to the outright put only. A spread has
    # different payoffs (capped loss and capped gain), so its EV is
    # checked separately on the spread numbers by the caller.
    if route == "outright" and ev_dollars is not None and ev_dollars <= PUT_EV_FLOOR:
        return {
            "decision": "excluded",
            "reasons": [
                f"expected value ${ev_dollars:.0f} per contract is not above zero, excluded"
            ],
            "ev_dollars": ev_dollars,
            "ev_per_dollar_risked": ev_per_dollar,
            "reward_risk": reward_risk,
            "fits_challenge": compute_fits_challenge(max_loss_per_contract, per_trade_cap_dollars),
            "put_variant": None,
        }

    return {
        "decision": route,
        "reasons": [route_reason],
        "ev_dollars": ev_dollars,
        "ev_per_dollar_risked": ev_per_dollar,
        "reward_risk": reward_risk,
        "fits_challenge": compute_fits_challenge(max_loss_per_contract, per_trade_cap_dollars),
        "put_variant": route,
    }


def put_prob_profit(price: float, long_strike: float, net_debit: float,
                    dte: int, iv_pct: float) -> float | None:
    """P(profit) for a bear spread: P(stock finishes below breakeven).

    Breakeven is the long strike minus the net debit. This is the same
    Black-Scholes d2 probability used for outright puts, applied to the
    spread breakeven; it ignores the capped gain, so it is an
    approximation, labelled as such wherever shown.
    """
    return compute_prob_profit(price, long_strike, net_debit, dte, iv_pct, "PUT")


def put_plain_copy(ticker: str, strike: float, expiry: str, premium: float,
                   max_loss: float, target, stop, breakeven: float,
                   variant: str, spread: dict | None = None) -> list[str]:
    """Plain-language lines for a put card. No unexplained jargon."""
    lines = []
    if variant == "bear_spread" and spread:
        long_strike = spread.get("long_strike", strike)
        short_strike = spread.get("short_strike")
        lines.append(
            f"Bear spread on {ticker}: you pay ${spread['net_debit']:.2f} per share "
            f"(${spread['net_debit'] * 100:.0f} per contract) to buy the ${long_strike:.0f} "
            f"put and sell the ${short_strike:.0f} put, expiring {expiry}."
        )
        lines.append(
            f"The most you can lose is ${spread['max_loss']:.0f} per contract, and the most "
            f"you can gain is ${spread['max_gain']:.0f} per contract. The loss is capped "
            "because the put you sold offsets the put you bought."
        )
        lines.append(
            f"You make money if {ticker} finishes below ${breakeven:.2f} by expiry. "
            "Volatility was too high to buy a put on its own, so this spread "
            "limits what you pay for it."
        )
    else:
        lines.append(
            f"Long put on {ticker}: you pay ${premium:.2f} per share "
            f"(${premium * 100:.0f} per contract) to buy the ${strike:.0f} put, "
            f"expiring {expiry}."
        )
        lines.append(
            f"The most you can lose is ${max_loss:.0f} per contract, and that "
            "happens if the stock stays above the strike and the put expires "
            "worthless. You make money if the stock finishes below "
            f"${breakeven:.2f} by expiry."
        )
    if target is not None:
        lines.append(
            f"Target: the stock falls to about ${target:.2f}. "
            "That is where the trade is expected to pay off."
        )
    if stop is not None:
        lines.append(
            f"Exit if the stock closes above ${stop:.2f}. That means the "
            "downward move failed, so the trade is closed before it loses more."
        )
    return lines


def invalidation_text_put(stop: float | None) -> str | None:
    """Invalidation line for a put: the stock rising through the stop."""
    if stop is None:
        return None
    return f"Stock closes above ${stop:.2f}"
