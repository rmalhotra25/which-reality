"""
Phase 3A directional options ranking.

Pure math functions. No DB, no API calls.

RANKING (printed on every card, see RANKING_FORMULA_TEXT):
  EV per contract = P(profit) x payoff at target - (1 - P(profit)) x max loss
  rank by EV per $ risked = EV / max loss per contract

  P(profit) is a real Black-Scholes probability from the chosen contract's own
  implied volatility, not delta: P(stock finishes past breakeven), where
  breakeven = strike + entry premium for a bought call (strike - premium for
  a bought put). Delta is shown separately, labeled as the chance of finishing
  above (CALL) or below (PUT) the strike.

  There is exactly one reward/risk figure: payoff at target / |payoff at stop|.
  The stop is a premium stop: the stock level where the option is worth 50% of
  the entry premium, at least one expected move away from entry. The -50%
  premium loss at the stop therefore follows from the stop definition.

  The old weighted 0-100 blend (0.30 delta, 0.35 stock-distance R/R, 0.20 IV,
  0.15 trend) is gone as a ranking input. Its four factors survive only as
  diagnostics in compute_ranking_components, and the IV diagnostic is hidden
  (None) while IV history is still building: the placeholder 50 is never fed
  into any score. Spread cost is never subtracted: bid/ask are 0.0 on this
  data plan (no quotes entitlement), so the spread is unknown.
"""
import math


RANKING_FORMULA_TEXT = (
    "EV = P(profit) x payoff at target - (1 - P(profit)) x max loss  |  "
    "rank by EV per $ risked = EV / max loss  |  "
    "P(profit) = P(stock finishes past breakeven) from Black-Scholes d2 at the contract IV  |  "
    "R/R = payoff at target / |payoff at stop| (one figure, everywhere)  |  "
    "spread unknown (no live quotes), so no spread cost is subtracted  |  "
    "IV score hidden while IV history is building, never a placeholder 50"
)

# Risk tiers are calibrated to real P(profit), not delta. Bought slightly-OTM
# calls typically land at P(profit) 0.15-0.40, so the old delta thresholds
# (0.65 / 0.45) would have bucketed nearly everything "higher risk" and told
# the user nothing. These thresholds still discriminate: a candidate needs a
# genuine 40%+ chance of finishing past breakeven to read "lower risk".
TIER_LOWER_MIN = 0.40
TIER_BALANCED_MIN = 0.25


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def determine_direction(technicals: dict) -> str:
    """Return 'CALL' for bullish setups, 'PUT' for bearish. Majority-vote on three signals."""
    ma = technicals.get("moving_averages") or {}
    macd = technicals.get("macd") or {}
    rsi = technicals.get("rsi") or 50

    above_ma50 = ma.get("above_ma50", True)
    crossover = macd.get("crossover", "neutral")

    bullish = 0
    bearish = 0

    if above_ma50:
        bullish += 1
    else:
        bearish += 1

    if crossover == "bullish":
        bullish += 1
    elif crossover == "bearish":
        bearish += 1

    if rsi <= 50:
        bullish += 1
    else:
        bearish += 1

    return "CALL" if bullish >= bearish else "PUT"


def bs_call_delta(S: float, K: float, T: float, sigma: float, r: float = 0.045) -> float:
    """Black-Scholes delta for a call option."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.5
    sigma_sqrtT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / sigma_sqrtT
    return _norm_cdf(d1)


def bs_put_delta_abs(S: float, K: float, T: float, sigma: float, r: float = 0.045) -> float:
    """Absolute delta for a put option (|delta_put| = 1 - delta_call)."""
    return 1.0 - bs_call_delta(S, K, T, sigma, r)


def bs_option_price(S: float, K: float, T: float, sigma: float,
                    option_type: str, r: float = 0.045) -> float:
    """Black-Scholes price of a European call or put. Used for the premium stop
    (bisection on S) and as a regression guard for IV consistency: the price
    implied by an IV must roughly reproduce the premium actually paid."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    sigma_sqrtT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / sigma_sqrtT
    d2 = d1 - sigma_sqrtT
    discount = math.exp(-r * T)
    if option_type.upper() == "CALL":
        return max(S * _norm_cdf(d1) - K * discount * _norm_cdf(d2), 0.0)
    return max(K * discount * _norm_cdf(-d2) - S * _norm_cdf(-d1), 0.0)


def bs_call_price(S: float, K: float, T: float, sigma: float, r: float = 0.045) -> float:
    """Black-Scholes price of a European call."""
    return bs_option_price(S, K, T, sigma, "CALL", r)


def compute_delta(price: float, strike: float, dte: int, annual_iv_pct: float,
                  option_type: str) -> float:
    """Return absolute delta (0-1) for the option using Black-Scholes."""
    T = dte / 365.0
    sigma = (annual_iv_pct or 30.0) / 100.0
    if option_type.upper() == "CALL":
        return bs_call_delta(price, strike, T, sigma)
    return bs_put_delta_abs(price, strike, T, sigma)


def compute_expected_move(price: float, atm_iv_pct: float, dte: int) -> tuple[float, float]:
    """
    One-standard-deviation expected move via ATM straddle approximation.
    straddle_mid = S * sigma * sqrt(T) * 0.7979  (= 2 * N'(0) = 2 * (1/sqrt(2pi)))
    Returns (dollars, percent).
    """
    if not price or not atm_iv_pct or dte <= 0:
        return (0.0, 0.0)
    sigma = atm_iv_pct / 100.0
    T = dte / 365.0
    dollars = round(price * sigma * math.sqrt(T) * 0.7979, 2)
    pct = round(dollars / price * 100, 2) if price else 0.0
    return (dollars, pct)


def compute_payoffs(option_type: str, strike: float, entry_premium: float,
                    underlying_target: float | None,
                    underlying_stop: float | None) -> tuple[float, float, float]:
    """
    Payoffs per contract (premium * 100).

    at_target:    intrinsic value at underlying_target minus premium paid.
    at_stop:      -50% of premium. This is not an arbitrary convention: the
                  stop is defined as the stock level where the option is worth
                  50% of the entry premium (see compute_premium_stop), so the
                  -50% loss at the stop follows from the stop definition.
    at_unchanged: -entry_premium * 100 (option expires worthless, full loss).
    """
    max_loss = round(-entry_premium * 100, 0)

    if underlying_target is not None and strike:
        if option_type.upper() == "CALL":
            intrinsic = max(underlying_target - strike, 0.0)
        else:
            intrinsic = max(strike - underlying_target, 0.0)
        at_target = round((intrinsic - entry_premium) * 100, 0)
    else:
        at_target = None

    at_stop = round(-entry_premium * 100 * 0.50, 0)  # 50% premium stop, per contract
    at_unchanged = max_loss

    return (at_target, at_stop, at_unchanged)


def compute_premium_stop(entry_price: float, strike: float, entry_premium: float,
                         dte: int, iv_pct: float, option_type: str,
                         expected_move_dollars: float) -> float | None:
    """
    Premium-based stop: the stock price at which the option is worth 50% of
    the entry premium at current DTE, found by bisection on S with
    Black-Scholes at the contract IV. The stop is then enforced to sit at
    least one expected move away from entry, so ordinary noise does not
    trigger it: for a CALL the stop is at most entry - one expected move,
    for a PUT at least entry + one expected move.

    Returns the stop level, or None when the inputs cannot support one.
    """
    if not entry_price or entry_price <= 0 or not entry_premium or entry_premium <= 0:
        return None
    if dte <= 0 or not iv_pct or iv_pct <= 0:
        return None
    T = dte / 365.0
    sigma = iv_pct / 100.0
    target_value = 0.5 * entry_premium
    em = expected_move_dollars or 0.0

    is_call = option_type.upper() == "CALL"
    # Bisection bracket: the option loses value as the stock moves against the
    # position, so search away from entry in the adverse direction.
    if is_call:
        lo, hi = max(0.05, entry_price * 0.30), entry_price
    else:
        lo, hi = entry_price, entry_price * 1.70 + 1.0

    def value_at(s: float) -> float:
        return bs_option_price(s, strike, T, sigma, option_type)

    # If the option is already worth less than half the premium at entry
    # (entry premium was estimated with a different vol), fall back to the
    # one-expected-move level rather than inventing a stop above entry.
    if is_call and value_at(hi) <= target_value:
        return round(entry_price - em, 2) if em > 0 else None
    if not is_call and value_at(lo) <= target_value:
        return round(entry_price + em, 2) if em > 0 else None
    # If it is still worth more than half even at the bracket edge, take the edge.
    if is_call and value_at(lo) >= target_value:
        stop = lo
    elif not is_call and value_at(hi) >= target_value:
        stop = hi
    else:
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if is_call:
                # value falls as S falls: mid too high when value > target
                if value_at(mid) > target_value:
                    hi = mid
                else:
                    lo = mid
            else:
                # value falls as S rises: mid too low when value > target
                if value_at(mid) > target_value:
                    lo = mid
                else:
                    hi = mid
        stop = (lo + hi) / 2.0

    # Enforce at least one expected move of distance from entry.
    if em > 0:
        if is_call:
            stop = min(stop, entry_price - em)
        else:
            stop = max(stop, entry_price + em)
    return round(stop, 2)


# ---------------------------------------------------------------------------
# Real probabilities from the contract's own IV
# ---------------------------------------------------------------------------

def _d2_finish(S: float, level: float, T: float, sigma: float, r: float = 0.045) -> float:
    """Black-Scholes d2 for finishing beyond `level`."""
    return (math.log(S / level) + (r - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def compute_prob_profit(S: float, K: float, entry_premium: float, dte: int,
                        iv_pct: float, option_type: str) -> float | None:
    """
    Real probability of profit for a bought option: P(stock finishes past
    breakeven) via Black-Scholes d2 at the contract IV.
    breakeven = strike + entry premium (CALL), strike - entry premium (PUT).
    This is strictly lower than abs(delta) for an OTM bought option, because
    delta is only P(finishing past the strike), while profit also needs the
    premium back. Returns None when the inputs cannot support an estimate.
    """
    if not S or S <= 0 or not K or K <= 0 or entry_premium is None or entry_premium < 0:
        return None
    if dte is None or dte <= 0 or not iv_pct or iv_pct <= 0:
        return None
    T = dte / 365.0
    sigma = iv_pct / 100.0
    if option_type.upper() == "CALL":
        breakeven = K + entry_premium
        if breakeven <= 0:
            return None
        p = _norm_cdf(_d2_finish(S, breakeven, T, sigma))
    else:
        breakeven = K - entry_premium
        if breakeven <= 0:
            return None
        p = _norm_cdf(-_d2_finish(S, breakeven, T, sigma))
    return round(max(0.01, min(0.99, p)), 3)


def compute_prob_touch(S: float, level: float, dte: int, iv_pct: float,
                       is_upper: bool) -> float | None:
    """
    Approximate probability the stock touches `level` before expiry, via the
    reflection principle at zero drift: P(touch) is approximately 2x the
    probability of finishing beyond the level. Labeled approximate wherever
    it is shown. Returns None when the inputs cannot support an estimate.
    """
    if not S or S <= 0 or not level or level <= 0:
        return None
    if dte is None or dte <= 0 or not iv_pct or iv_pct <= 0:
        return None
    T = dte / 365.0
    sigma = iv_pct / 100.0
    if is_upper:
        if level <= S:
            return 0.99  # already at or past the level
        p_finish = _norm_cdf(math.log(S / level) / (sigma * math.sqrt(T)))
    else:
        if level >= S:
            return 0.99  # already at or past the level
        p_finish = _norm_cdf(math.log(level / S) / (sigma * math.sqrt(T)))
    return round(max(0.01, min(0.99, 2.0 * p_finish)), 3)


def compute_expected_value(prob_profit: float | None, payoff_at_target: float | None,
                           max_loss_per_contract: float | None
                           ) -> tuple[float | None, float | None]:
    """
    Real expectancy in dollars per contract:
      EV = P(profit) x payoff at target - (1 - P(profit)) x max loss
    Returns (ev_dollars, ev_per_dollar_risked = EV / max loss). Either is None
    when the inputs cannot support it. A negative EV is a real result, not an
    error: it means the trade loses money on average at these prices.
    """
    if prob_profit is None or payoff_at_target is None or max_loss_per_contract is None:
        return (None, None)
    loss = abs(max_loss_per_contract)
    if loss <= 0:
        return (None, None)
    ev = prob_profit * payoff_at_target - (1.0 - prob_profit) * loss
    return (round(ev, 2), round(ev / loss, 3))


# ---------------------------------------------------------------------------
# Diagnostic component scores (display only, never ranking inputs)
# ---------------------------------------------------------------------------

def score_probability(prob_profit: float | None) -> float | None:
    """Diagnostic: real P(profit) on a 0-100 scale. None when unknown."""
    if prob_profit is None:
        return None
    return _clamp(prob_profit * 100)


def score_reward_to_risk(payoff_at_target: float | None,
                         payoff_at_stop: float | None) -> float | None:
    """
    Diagnostic: the single R/R multiple (payoff at target / |payoff at stop|)
    scaled so 3:1 earns 100, 2:1 earns 67, 1:1 earns 33. None when unknown.
    """
    rr = compute_reward_risk(payoff_at_target, payoff_at_stop)
    if rr is None:
        return None
    return _clamp(rr / 3.0 * 100)


def score_iv_context(iv_percentile: float | None, iv_available: bool,
                     iv_history_building: bool = False) -> float | None:
    """
    Diagnostic: reward cheap IV (low percentile = good time to buy premium).
    Top-quartile IV receives a stated penalty. Returns None when IV history
    is still building or no IV data exists: the placeholder 50 is never fed
    into any score, silently or otherwise.
    """
    if iv_history_building or not iv_available or iv_percentile is None:
        return None
    if iv_percentile < 25:
        return 100.0
    if iv_percentile < 50:
        return 90.0
    if iv_percentile < 75:
        return 70.0
    if iv_percentile < 90:
        return 40.0   # top-quartile penalty
    return 15.0       # very elevated IV


def score_trend_alignment(above_ma50: bool | None, above_ma200: bool | None,
                           option_type: str) -> float:
    """
    Diagnostic: CALL above both MAs = strong trend alignment; PUT mirrors.
    Unknown values return 50.
    """
    if above_ma50 is None or above_ma200 is None:
        return 50.0

    if option_type.upper() == "CALL":
        if above_ma50 and above_ma200:
            return 100.0
        if above_ma200 and not above_ma50:
            return 70.0
        if above_ma50 and not above_ma200:
            return 60.0
        return 20.0  # below both MAs, bullish play against trend
    else:  # PUT
        if not above_ma50 and not above_ma200:
            return 100.0
        if not above_ma200 and above_ma50:
            return 70.0
        if not above_ma50 and above_ma200:
            return 60.0
        return 20.0  # above both MAs, bearish play against trend


# ---------------------------------------------------------------------------
# Risk tiers (presentation only; never ranking inputs)
# ---------------------------------------------------------------------------

TIER_LABELS = {"lower": "Lower risk", "balanced": "Balanced", "higher": "Higher risk"}


def compute_reward_risk(payoff_at_target: float | None,
                        payoff_at_stop: float | None) -> float | None:
    """
    The one reward-to-risk multiple, used identically on the card, in the
    analysis text, and in the score input: payoff at target divided by the
    absolute payoff at the stop. Both inputs are per-contract dollars, so the
    units cancel. A missing payoff, a zero stop loss, or a negative payoff at
    target returns None. (The old version divided by max loss instead, which
    is why the card once showed 1.3x while the analysis text showed 2.5x.)
    """
    if payoff_at_target is None or payoff_at_stop is None:
        return None
    loss = abs(payoff_at_stop)
    if loss <= 0 or payoff_at_target < 0:
        return None
    return round(payoff_at_target / loss, 2)


def compute_risk_tier(prob_profit: float | None) -> str | None:
    """
    Bucket a candidate by real probability of profit ONLY. Reward-to-risk is
    displayed beside the tier but never moves a candidate between tiers:
    a low-probability trade stays "higher" no matter how large the payoff.
    Thresholds are calibrated to P(profit) (see TIER_LOWER_MIN /
    TIER_BALANCED_MIN above), not to delta. Returns "lower", "balanced",
    "higher", or None when there is no probability estimate.
    """
    if prob_profit is None:
        return None
    if prob_profit >= TIER_LOWER_MIN:
        return "lower"
    if prob_profit >= TIER_BALANCED_MIN:
        return "balanced"
    return "higher"


def compute_fits_challenge(max_loss_per_contract: float | None,
                           per_trade_cap_dollars: float | None) -> bool:
    """
    True when one contract's max loss fits inside the Challenge per-trade
    risk cap. max_loss_per_contract is already a per-contract dollar figure
    (entry premium x 100). A missing max loss, or an unavailable cap (no
    initialized Challenge account), never fits.
    """
    if max_loss_per_contract is None or per_trade_cap_dollars is None:
        return False
    return abs(max_loss_per_contract) <= per_trade_cap_dollars + 1e-9


def compute_ranking_components(
    prob_profit: float | None,
    payoff_at_target: float | None,
    payoff_at_stop: float | None,
    max_loss_per_contract: float | None,
    iv_percentile: float | None,
    iv_available: bool,
    iv_history_building: bool,
    above_ma50: bool | None,
    above_ma200: bool | None,
    option_type: str,
) -> dict:
    """
    Rank by real expectancy: score is EV per $ risked (EV / max loss).
    The four old blend factors survive only as diagnostics and never
    influence the rank. When IV history is building, the IV diagnostic is
    None and excluded; no placeholder feeds the rank.
    """
    ev_dollars, ev_per_dollar = compute_expected_value(
        prob_profit, payoff_at_target, max_loss_per_contract
    )
    reward_risk = compute_reward_risk(payoff_at_target, payoff_at_stop)
    prob_diag = score_probability(prob_profit)
    rr_diag = score_reward_to_risk(payoff_at_target, payoff_at_stop)
    iv_diag = score_iv_context(iv_percentile, iv_available, iv_history_building)
    trend = score_trend_alignment(above_ma50, above_ma200, option_type)

    return {
        "score": ev_per_dollar,
        "ev_dollars": ev_dollars,
        "ev_per_dollar_risked": ev_per_dollar,
        "prob_profit": prob_profit,
        "reward_risk": reward_risk,
        "prob_score": round(prob_diag, 1) if prob_diag is not None else None,
        "rr_score": round(rr_diag, 1) if rr_diag is not None else None,
        "iv_context_score": round(iv_diag, 1) if iv_diag is not None else None,
        "iv_excluded_from_ranking": bool(iv_history_building or not iv_available),
        "trend_score": round(trend, 1),
        "formula": RANKING_FORMULA_TEXT,
        "inputs": {
            "iv_percentile": iv_percentile,
            "iv_available": iv_available,
            "iv_history_building": iv_history_building,
            "above_ma50": above_ma50,
            "above_ma200": above_ma200,
            "option_type": option_type,
            "payoff_at_target": payoff_at_target,
            "payoff_at_stop": payoff_at_stop,
            "max_loss_per_contract": max_loss_per_contract,
        },
        "weights": None,
    }
