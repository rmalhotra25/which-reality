"""
Phase 3A directional options ranking.

Pure math functions. No DB, no API calls.

RANKING FORMULA (printed on every card):
  score = probability * 0.30 + reward_to_risk * 0.35 + iv_context * 0.20 + trend * 0.15

Components:
  probability    delta_abs * 100 (0-100). Higher delta = higher PoP.
  reward_to_risk (target_dist / stop_dist) / 3.0 * 100, capped 100.
                 3:1 = 100 pts; 2:1 = 67; 1:1 = 33.
  iv_context     pct < 25 -> 100; 25-49 -> 90; 50-74 -> 70; 75-89 -> 40 (top-quartile
                 penalty, buying elevated IV); 90+ -> 15. No data -> 50.
  trend          CALL: above MA50+MA200 -> 100, above MA200 only -> 70,
                 above MA50 only -> 60, below both -> 20.
                 PUT: mirror (bearish alignment rewarded).
"""
import math


RANKING_FORMULA_TEXT = (
    "score = probability×0.30 + reward_to_risk×0.35 + iv_context×0.20 + trend×0.15  |  "
    "probability = delta_abs×100;  "
    "R/R = (target_dist / stop_dist) / 3.0 × 100, cap 100;  "
    "IV context: pct<25→100, 25-49→90, 50-74→70, 75-89→40 (penalty), ≥90→15, no data→50;  "
    "trend (CALL): above MA50+MA200→100, MA200 only→70, MA50 only→60, below both→20; PUT mirrors"
)


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
    at_stop:      -50% of premium (convention: close at half-loss before full expiry).
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

    at_stop = round(-entry_premium * 100 * 0.50, 0)  # 50% stop loss per contract
    at_unchanged = max_loss

    return (at_target, at_stop, at_unchanged)


# ---------------------------------------------------------------------------
# Ranking component scores (each returns 0-100)
# ---------------------------------------------------------------------------

def score_probability(delta_abs: float) -> float:
    """Higher absolute delta = higher probability of being profitable. Score = delta * 100."""
    return _clamp(delta_abs * 100)


def score_reward_to_risk(underlying_entry: float | None, underlying_target: float | None,
                          underlying_stop: float | None) -> float:
    """3:1 earns 100; 2:1 earns 67; 1:1 earns 33; <1:1 scores linearly down."""
    if not underlying_entry or not underlying_target or not underlying_stop:
        return 50.0
    target_dist = abs(underlying_target - underlying_entry)
    stop_dist = abs(underlying_entry - underlying_stop)
    if stop_dist <= 0:
        return 50.0
    rr = target_dist / stop_dist
    return _clamp(rr / 3.0 * 100)


def score_iv_context(iv_percentile: float | None, iv_available: bool) -> float:
    """
    Reward cheap IV (low percentile = good time to buy premium).
    Top-quartile IV receives a stated penalty.
    """
    if not iv_available or iv_percentile is None:
        return 50.0
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
    CALL: above both MAs = strong trend alignment.
    PUT:  below both MAs = strong bearish alignment (scores mirror).
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


def compute_prob_profit(delta_abs: float | None) -> float | None:
    """
    Probability-of-profit proxy for a long-premium candidate.
    Uses abs(delta), the same convention as score_probability, clamped to
    0.01-0.99. A missing or zero delta returns None: no estimate is shown
    rather than a fabricated one.
    """
    if not delta_abs:
        return None
    return round(max(0.01, min(0.99, abs(delta_abs))), 3)


def compute_reward_risk(payoff_at_target: float | None,
                        max_loss_per_contract: float | None) -> float | None:
    """
    Reward-to-risk multiple: payoff at target divided by max loss.
    Both inputs are per-contract dollars (payoff_at_target is net P&L per
    contract, max_loss_per_contract is entry premium x 100), so the units
    cancel. A missing or zero max loss, or a missing or negative payoff at
    target, returns None.
    """
    if payoff_at_target is None or max_loss_per_contract is None:
        return None
    loss = abs(max_loss_per_contract)
    if loss <= 0 or payoff_at_target < 0:
        return None
    return round(payoff_at_target / loss, 2)


def compute_risk_tier(prob_profit: float | None) -> str | None:
    """
    Bucket a candidate by probability of profit ONLY. Reward-to-risk is
    displayed beside the tier but never moves a candidate between tiers:
    a low-probability trade stays "higher" no matter how large the payoff.
    Returns "lower", "balanced", "higher", or None when there is no
    probability estimate.
    """
    if prob_profit is None:
        return None
    if prob_profit >= 0.65:
        return "lower"
    if prob_profit >= 0.45:
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
    delta_abs: float,
    underlying_entry: float | None,
    underlying_target: float | None,
    underlying_stop: float | None,
    iv_percentile: float | None,
    iv_available: bool,
    above_ma50: bool | None,
    above_ma200: bool | None,
    option_type: str,
) -> dict:
    """
    Compute all four ranking components and the final weighted score.
    Returns a dict with component scores and the full formula breakdown.
    """
    prob = score_probability(delta_abs)
    rr = score_reward_to_risk(underlying_entry, underlying_target, underlying_stop)
    iv = score_iv_context(iv_percentile, iv_available)
    trend = score_trend_alignment(above_ma50, above_ma200, option_type)

    score = _clamp(prob * 0.30 + rr * 0.35 + iv * 0.20 + trend * 0.15)

    return {
        "score": round(score, 1),
        "prob_score": round(prob, 1),
        "rr_score": round(rr, 1),
        "iv_context_score": round(iv, 1),
        "trend_score": round(trend, 1),
        "formula": RANKING_FORMULA_TEXT,
        "inputs": {
            "delta_abs": round(delta_abs, 3),
            "iv_percentile": iv_percentile,
            "iv_available": iv_available,
            "above_ma50": above_ma50,
            "above_ma200": above_ma200,
            "option_type": option_type,
            "target_dist": (
                round(abs((underlying_target or 0) - (underlying_entry or 0)), 2)
                if underlying_target and underlying_entry else None
            ),
            "stop_dist": (
                round(abs((underlying_entry or 0) - (underlying_stop or 0)), 2)
                if underlying_entry and underlying_stop else None
            ),
        },
        "weights": {"probability": 0.30, "reward_to_risk": 0.35, "iv_context": 0.20, "trend": 0.15},
    }
