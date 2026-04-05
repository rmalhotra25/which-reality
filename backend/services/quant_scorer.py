"""
Quantitative scoring engine.

Each function takes pre-computed technical indicator data and returns
a score between 0-100 based purely on mathematical rules — no AI involved.
These scores are passed to Claude alongside the raw indicators so that
Claude's qualitative score adjusts from an anchored baseline.
"""


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def score_rsi(rsi: float | None, mode: str = "mean_reversion") -> float:
    """
    mode='mean_reversion' (options/wheel): reward oversold, penalise overbought.
    mode='trend' (long-term): reward healthy 45-65 range, penalise extremes.
    """
    if rsi is None:
        return 50.0
    if mode == "mean_reversion":
        if rsi <= 25:   return 95.0   # extremely oversold — strong call/put-sell signal
        if rsi <= 35:   return 85.0
        if rsi <= 45:   return 70.0
        if rsi <= 55:   return 60.0
        if rsi <= 65:   return 45.0
        if rsi <= 75:   return 30.0
        return 15.0                   # overbought — dangerous entry
    else:  # trend
        if 45 <= rsi <= 65: return 80.0   # healthy uptrend momentum
        if 35 <= rsi < 45:  return 65.0   # slight weakness but ok
        if 65 < rsi <= 75:  return 55.0   # extended but not extreme
        if rsi > 75:        return 30.0   # overbought — wait for pullback
        return 25.0                        # below 35 — weakening trend


def score_macd(macd: dict | None) -> float:
    """Reward bullish crossover and positive histogram; penalise bearish."""
    if not macd:
        return 50.0
    crossover = macd.get("crossover", "neutral")
    histogram = macd.get("histogram", 0) or 0
    base = {"bullish": 80.0, "neutral": 50.0, "bearish": 25.0}.get(crossover, 50.0)
    # Boost if histogram is growing (momentum accelerating)
    if histogram > 0.5:   base = min(base + 10, 100)
    elif histogram < -0.5: base = max(base - 10, 0)
    return base


def score_moving_averages(ma: dict | None, mode: str = "options") -> float:
    """
    options/wheel: strong uptrend required (above MA50+200 = bullish).
    longterm: golden cross + above MA200 is the gold standard.
    """
    if not ma:
        return 50.0
    above50  = ma.get("above_ma50", None)
    above200 = ma.get("above_ma200", None)
    golden   = ma.get("golden_cross", None)
    death    = ma.get("death_cross", None)

    if mode == "longterm":
        if golden and above200 and above50:  return 95.0
        if above200 and above50:             return 80.0
        if above200 and not above50:         return 55.0
        if not above200 and above50:         return 40.0
        if death:                            return 10.0
        return 25.0
    else:
        if above50 and above200:   return 85.0
        if above50 and not above200: return 60.0
        if not above50 and above200: return 40.0
        if death:                    return 10.0
        return 25.0


def score_fibonacci_proximity(price: float | None, fib: dict | None) -> float:
    """
    How close is the current price to a key Fibonacci support level?
    Closer = higher score (good entry near support).
    """
    if not fib or not price:
        return 50.0
    levels = [
        fib.get("fib_382"),
        fib.get("fib_500"),
        fib.get("fib_618"),
        fib.get("fib_786"),
    ]
    levels = [l for l in levels if l is not None]
    if not levels:
        return 50.0
    # Find closest Fib support below price
    support_levels = [l for l in levels if l <= price]
    if not support_levels:
        return 40.0
    closest = max(support_levels)
    distance_pct = ((price - closest) / price) * 100
    if distance_pct <= 1.0:  return 95.0   # sitting right on support
    if distance_pct <= 2.5:  return 85.0
    if distance_pct <= 5.0:  return 70.0
    if distance_pct <= 8.0:  return 55.0
    return 40.0


def score_bollinger(bb: dict | None) -> float:
    """
    %B near 0 (at lower band) = oversold buy signal.
    %B near 1 (at upper band) = overbought.
    Squeeze = bonus for potential explosive move.
    """
    if not bb:
        return 50.0
    pct_b   = bb.get("pct_b", 0.5) or 0.5
    squeeze = bb.get("squeeze", False)
    if pct_b <= 0.10:   base = 90.0   # at/below lower band — oversold
    elif pct_b <= 0.25: base = 75.0
    elif pct_b <= 0.45: base = 65.0
    elif pct_b <= 0.60: base = 55.0
    elif pct_b <= 0.80: base = 40.0
    else:               base = 25.0   # at/above upper band — overbought
    if squeeze:
        base = min(base + 15, 100)    # squeeze = potential breakout bonus
    return base


def score_volume_trend(vol: dict | None) -> float:
    """High volume = conviction; low volume = weak signal."""
    if not vol:
        return 50.0
    ratio = vol.get("ratio", 1.0) or 1.0
    if ratio >= 2.0:   return 90.0   # very high volume — strong conviction
    if ratio >= 1.5:   return 75.0
    if ratio >= 1.0:   return 60.0
    if ratio >= 0.7:   return 50.0
    return 35.0                       # very low volume — weak signal


def score_iv_rank(iv_rank: float | None, mode: str = "wheel") -> float:
    """
    wheel: wants IV rank 30-70 (elevated but not extreme).
    options: wants IV rank 20-50 (buy options when IV is not too high).
    """
    if iv_rank is None:
        return 50.0
    if mode == "wheel":
        if 40 <= iv_rank <= 65:  return 90.0   # sweet spot for selling premium
        if 30 <= iv_rank < 40:   return 75.0
        if 65 < iv_rank <= 80:   return 65.0   # high IV — good premium but risky
        if iv_rank > 80:         return 40.0   # crisis-level IV — dangerous
        return 30.0                             # low IV — poor premium
    else:  # buying options
        if 20 <= iv_rank <= 40:  return 85.0   # cheap options = good to buy
        if 40 < iv_rank <= 55:   return 65.0
        if iv_rank > 55:         return 35.0   # expensive options = poor R/R
        return 55.0                             # very low IV — options cheap but no catalyst


def score_risk_reward(entry: float | None, exit_: float | None, stop: float | None) -> float:
    """Score the raw risk/reward ratio."""
    if not entry or not exit_ or not stop or entry <= stop:
        return 50.0
    rr = (exit_ - entry) / (entry - stop)
    if rr >= 3.0:   return 95.0
    if rr >= 2.5:   return 85.0
    if rr >= 2.0:   return 75.0
    if rr >= 1.5:   return 60.0
    if rr >= 1.0:   return 45.0
    return 25.0


# ---------------------------------------------------------------------------
# Tab-level composite scorers
# ---------------------------------------------------------------------------

def compute_options_quant_score(technicals: dict, entry: float | None = None,
                                 exit_: float | None = None, stop: float | None = None) -> dict:
    """
    Returns a dict with component scores and a weighted composite (0-100).
    """
    rsi_s   = score_rsi(technicals.get("rsi"), mode="mean_reversion")
    macd_s  = score_macd(technicals.get("macd"))
    ma_s    = score_moving_averages(technicals.get("moving_averages"), mode="options")
    fib_s   = score_fibonacci_proximity(technicals.get("price"), technicals.get("fibonacci"))
    bb_s    = score_bollinger(technicals.get("bollinger"))
    vol_s   = score_volume_trend(technicals.get("volume_trend"))
    iv_s    = score_iv_rank(technicals.get("iv_rank_approx"), mode="options")
    rr_s    = score_risk_reward(entry, exit_, stop)

    composite = _clamp(
        rsi_s   * 0.20 +
        macd_s  * 0.15 +
        ma_s    * 0.15 +
        fib_s   * 0.15 +
        bb_s    * 0.10 +
        vol_s   * 0.10 +
        iv_s    * 0.05 +
        rr_s    * 0.10
    )
    return {
        "composite": round(composite, 1),
        "components": {
            "rsi": round(rsi_s, 1),
            "macd": round(macd_s, 1),
            "trend": round(ma_s, 1),
            "fibonacci": round(fib_s, 1),
            "bollinger": round(bb_s, 1),
            "volume": round(vol_s, 1),
            "iv": round(iv_s, 1),
            "risk_reward": round(rr_s, 1),
        }
    }


def compute_wheel_quant_score(technicals: dict) -> dict:
    rsi_s   = score_rsi(technicals.get("rsi"), mode="mean_reversion")
    macd_s  = score_macd(technicals.get("macd"))
    ma_s    = score_moving_averages(technicals.get("moving_averages"), mode="options")
    fib_s   = score_fibonacci_proximity(technicals.get("price"), technicals.get("fibonacci"))
    vol_s   = score_volume_trend(technicals.get("volume_trend"))
    iv_s    = score_iv_rank(technicals.get("iv_rank_approx") or technicals.get("atm_iv"), mode="wheel")

    composite = _clamp(
        rsi_s  * 0.20 +
        macd_s * 0.15 +
        ma_s   * 0.25 +   # trend is most important for wheel
        fib_s  * 0.20 +   # support level placement
        vol_s  * 0.10 +
        iv_s   * 0.10
    )
    return {
        "composite": round(composite, 1),
        "components": {
            "rsi": round(rsi_s, 1),
            "macd": round(macd_s, 1),
            "trend": round(ma_s, 1),
            "fibonacci": round(fib_s, 1),
            "volume": round(vol_s, 1),
            "iv": round(iv_s, 1),
        }
    }


def compute_longterm_quant_score(technicals: dict, fundamentals: dict) -> dict:
    rsi_s  = score_rsi(technicals.get("rsi"), mode="trend")
    macd_s = score_macd(technicals.get("macd"))
    ma_s   = score_moving_averages(technicals.get("moving_averages"), mode="longterm")
    vol_s  = score_volume_trend(technicals.get("volume_trend"))

    # Fundamental component
    eps_growth = fundamentals.get("eps_growth_ttm") or 0
    rev_growth = fundamentals.get("revenue_growth_ttm") or 0
    div_yield  = fundamentals.get("div_yield") or 0
    inv_type   = fundamentals.get("investment_type", "growth")

    if inv_type == "income":
        # Income: dividend yield matters most
        if div_yield >= 0.05:    fund_s = 90.0
        elif div_yield >= 0.035: fund_s = 75.0
        elif div_yield >= 0.02:  fund_s = 60.0
        else:                    fund_s = 35.0
    else:
        # Growth: earnings growth matters most
        if eps_growth >= 0.30:   fund_s = 95.0
        elif eps_growth >= 0.15: fund_s = 80.0
        elif eps_growth >= 0.05: fund_s = 65.0
        elif eps_growth >= 0:    fund_s = 50.0
        else:                    fund_s = 25.0

    composite = _clamp(
        ma_s   * 0.30 +   # long-term trend is paramount
        fund_s * 0.30 +   # fundamentals equally important
        rsi_s  * 0.15 +
        macd_s * 0.15 +
        vol_s  * 0.10
    )
    return {
        "composite": round(composite, 1),
        "components": {
            "trend": round(ma_s, 1),
            "fundamentals": round(fund_s, 1),
            "rsi": round(rsi_s, 1),
            "macd": round(macd_s, 1),
            "volume": round(vol_s, 1),
        }
    }


def recommend_strategy_type(technicals: dict) -> str:
    """
    Recommend the most appropriate options strategy based on technical conditions.

    Returns one of:
      single_leg        — strong directional momentum (buy call or put outright)
      iron_condor       — range-bound, collect premium from both sides
      bull_put_spread   — mildly bullish, sell put spread for credit
      bear_call_spread  — mildly bearish, sell call spread for credit
      bull_call_spread  — moderately bullish, buy call spread for debit
      bear_put_spread   — moderately bearish, buy put spread for debit
    """
    rsi  = technicals.get("rsi") or 50
    macd = technicals.get("macd") or {}
    bb   = technicals.get("bollinger") or {}
    ma   = technicals.get("moving_averages") or {}
    iv   = technicals.get("iv_rank_approx") or technicals.get("atm_iv") or 30

    crossover = macd.get("crossover", "neutral")
    histogram = macd.get("histogram", 0) or 0
    pct_b     = bb.get("pct_b", 0.5) or 0.5
    squeeze   = bb.get("squeeze", False)
    above50   = ma.get("above_ma50", None)
    above200  = ma.get("above_ma200", None)

    # Strong directional — outright single-leg option is best
    strong_bull = rsi < 32 and crossover == "bullish"
    strong_bear = rsi > 68 and crossover == "bearish"
    if strong_bull or strong_bear:
        return "single_leg"

    # Breakout incoming (BB squeeze) — single leg for max leverage
    if squeeze and abs(histogram) > 0.3:
        return "single_leg"

    # Range-bound with elevated IV — iron condor
    range_bound = 40 <= rsi <= 60 and 0.25 <= pct_b <= 0.75 and crossover == "neutral"
    if range_bound and iv >= 35:
        return "iron_condor"

    # Mild bearish with high IV — credit spread (bear call)
    if rsi > 58 and (crossover == "bearish" or histogram < -0.1) and iv >= 30:
        return "bear_call_spread"

    # Mild bullish with high IV — credit spread (bull put)
    if rsi < 52 and (crossover == "bullish" or histogram > 0.1) and iv >= 30:
        return "bull_put_spread"

    # Moderate bearish — debit spread (bear put)
    if rsi > 60 and crossover == "bearish":
        return "bear_put_spread"

    # Moderate bullish — debit spread (bull call)
    if rsi < 45 and crossover == "bullish":
        return "bull_call_spread"

    # Default: single leg if no clear multi-leg setup
    return "single_leg"


def compute_entry_exit_multi_leg(technicals: dict, strategy: str) -> dict:
    """
    Calculate strikes, max profit, max loss, and breakevens for multi-leg strategies.
    All values are per-share (multiply by 100 for per-contract).
    """
    price = technicals.get("price")
    atr   = technicals.get("atr")
    fib   = technicals.get("fibonacci") or {}
    ma    = technicals.get("moving_averages") or {}

    if not price or not atr:
        return {"strategy_type": strategy}

    wing = round(atr * 1.5, 2)   # width of each spread wing (≈1.5 ATR)

    fib618  = fib.get("fib_618")
    fib382  = fib.get("fib_382")
    fib236  = fib.get("fib_236")
    ma50    = ma.get("ma50")
    ma200   = ma.get("ma200")

    result = {"strategy_type": strategy}

    if strategy == "iron_condor":
        # Short strangle 1 ATR out; wings 1.5 ATR further
        sc = round(price + atr, 2)         # short call
        lc = round(sc + wing, 2)           # long call (wing)
        sp = round(price - atr, 2)         # short put
        lp = round(sp - wing, 2)           # long put (wing)
        # Net credit: rough estimate (~30% of wing width each side)
        credit = round(wing * 0.30 * 2, 2)
        result.update({
            "short_call_strike": sc, "long_call_strike": lc,
            "short_put_strike": sp, "long_put_strike": lp,
            "net_credit": credit,
            "max_profit": round(credit * 100, 0),
            "max_loss": round((wing - credit) * 100, 0),
            "breakeven_low":  round(sp - credit, 2),
            "breakeven_high": round(sc + credit, 2),
        })

    elif strategy == "bull_put_spread":
        # Short put at Fib/MA support; long put = wing below
        sp = fib618 or ma50 or round(price - atr, 2)
        sp = round(sp, 2)
        lp = round(sp - wing, 2)
        credit = round(wing * 0.35, 2)
        result.update({
            "short_put_strike": sp, "long_put_strike": lp,
            "net_credit": credit,
            "max_profit": round(credit * 100, 0),
            "max_loss": round((wing - credit) * 100, 0),
            "breakeven_low": round(sp - credit, 2),
        })

    elif strategy == "bear_call_spread":
        # Short call at Fib/resistance; long call = wing above
        sc = fib236 or fib382 or round(price + atr, 2)
        if sc <= price:
            sc = round(price + atr, 2)
        sc = round(sc, 2)
        lc = round(sc + wing, 2)
        credit = round(wing * 0.35, 2)
        result.update({
            "short_call_strike": sc, "long_call_strike": lc,
            "net_credit": credit,
            "max_profit": round(credit * 100, 0),
            "max_loss": round((wing - credit) * 100, 0),
            "breakeven_high": round(sc + credit, 2),
        })

    elif strategy == "bull_call_spread":
        # Buy call near price; sell call = wing above
        lc = round(price, 2)
        sc = round(lc + wing, 2)
        debit = round(wing * 0.40, 2)
        result.update({
            "long_call_strike": lc, "short_call_strike": sc,
            "net_credit": -debit,
            "max_profit": round((wing - debit) * 100, 0),
            "max_loss": round(debit * 100, 0),
            "breakeven_high": round(lc + debit, 2),
        })

    elif strategy == "bear_put_spread":
        # Buy put near price; sell put = wing below
        lp = round(price, 2)
        sp = round(lp - wing, 2)
        debit = round(wing * 0.40, 2)
        result.update({
            "long_put_strike": lp, "short_put_strike": sp,
            "net_credit": -debit,
            "max_profit": round((wing - debit) * 100, 0),
            "max_loss": round(debit * 100, 0),
            "breakeven_low": round(lp - debit, 2),
        })

    else:  # single_leg — use regular entry/exit calc
        pass

    return result


def compute_entry_exit_options(technicals: dict, option_type: str = "CALL") -> dict:
    """
    Suggest entry/exit/stop for an options trade based purely on ATR and Fib levels.
    Claude will refine these with a specific strike and premium estimate.
    """
    price = technicals.get("price")
    atr   = technicals.get("atr")
    fib   = technicals.get("fibonacci", {})
    ma    = technicals.get("moving_averages", {})

    if not price or not atr:
        return {}

    if option_type.upper() == "CALL":
        # Entry near current price or Fib support; target = price + 1.5-2x ATR
        support    = fib.get("fib_618") or fib.get("fib_500") or (price - atr)
        target     = round(price + 2.0 * atr, 2)
        stop_level = round(support - 0.5 * atr, 2)
    else:  # PUT
        # Entry near current price; target = price - 1.5-2x ATR
        resistance = fib.get("fib_236") or fib.get("fib_382") or (price + atr)
        target     = round(price - 2.0 * atr, 2)
        stop_level = round(resistance + 0.5 * atr, 2)

    return {
        "underlying_entry": round(price, 2),
        "underlying_target": target,
        "underlying_stop": stop_level,
        "atr": atr,
        "expected_move_1atr": round(atr, 2),
    }


def compute_entry_exit_wheel(technicals: dict) -> dict:
    """Suggest put strike and breakeven for the wheel strategy."""
    price = technicals.get("price")
    atr   = technicals.get("atr")
    fib   = technicals.get("fibonacci", {})
    ma    = technicals.get("moving_averages", {})

    if not price:
        return {}

    # Ideal put strike = below Fib 61.8% support or MA50, whichever is lower
    fib_support = fib.get("fib_618") or fib.get("fib_500")
    ma50        = ma.get("ma50")
    ma200       = ma.get("ma200")

    candidates = [x for x in [fib_support, ma50] if x and x < price]
    suggested_strike = round(min(candidates), 2) if candidates else round(price * 0.93, 2)

    return {
        "current_price": round(price, 2),
        "suggested_put_strike": suggested_strike,
        "pct_otm": round(((price - suggested_strike) / price) * 100, 1),
        "key_support_ma200": ma200,
        "atr": atr,
    }


def compute_entry_exit_longterm(technicals: dict, fundamentals: dict) -> dict:
    """Suggest buy range and 12-month target for long-term plays."""
    price = technicals.get("price")
    ma200 = (technicals.get("moving_averages") or {}).get("ma200")
    fib   = technicals.get("fibonacci", {})
    atr   = technicals.get("atr")

    if not price:
        return {}

    # Buy zone: current price or pullback to MA50
    ma50 = (technicals.get("moving_averages") or {}).get("ma50")
    buy_zone_low  = round(fib.get("fib_382") or (ma50 or price * 0.95), 2)
    buy_zone_high = round(price * 1.02, 2)  # up to 2% above current = fine to enter

    # Invalidation: close below MA200 = thesis broken
    stop_level = round((ma200 or price * 0.85) * 0.98, 2)  # 2% below MA200

    return {
        "current_price": round(price, 2),
        "buy_zone_low": buy_zone_low,
        "buy_zone_high": buy_zone_high,
        "invalidation_stop": stop_level,
        "ma200": ma200,
    }
