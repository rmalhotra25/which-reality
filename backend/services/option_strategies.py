"""Options Strategies section for ticker lookup, snapshot and on-demand.

Additional information only. This section never changes the
timing verdict, the long-term verdict, the DCA decision, or the
existing verdict put and call gating. The verdict put is a sell
put and the verdict call is a buy call, gated as before. The
strategies here are model-ranked, not predictions and not a
guarantee of profit: the ranking score below is a transparent
rule, and the selected play shows its ranking inputs in the
details view so the reason it ranked first can be checked.

Expiry rule, stated: one expiry for the whole section, the
listed expiry closest to 21 days to expiry among the supplied
chain rows, ties broken by the earliest expiry. If no listed
chain rows exist, or no strategy can be built from them, that
strategy reads as unavailable with a named reason, never with
fabricated strikes.

Greeks, only what the chain carries:
- Polygon rows carry delta, gamma, theta (as theta_seller, a
  positive number meaning income per share per day to the
  seller), vega, IV, bid, ask, mid, open interest, and volume.
- yfinance fallback rows carry delta and theta_seller computed
  by Black-Scholes from IV in the chain provider, and gamma
  and vega are None. This module never estimates a missing
  Greek itself: a None Greek is reported as Missing in the
  payload, and net Greeks are Missing when any leg is missing
  that Greek. The one exception the caller must know: delta
  and theta on a yfinance fallback row are Black-Scholes
  estimates made by the chain provider, not exchange Greeks,
  so the frontend labels the chain source, and this module
  does not claim otherwise.

Pricing, reused from the verdict gates:
- A bought option is priced at the ask when there is one, else
  the mid, labelled, never a last trade as executable.
- A sold option is priced at the bid, never a last trade.
- Liquidity quality, where known: spread at most 15% and open
  interest at least 100, the same thresholds as the verdict
  put gate. A row failing either is excluded from ranking,
  not ranked with a warning, because a wide or illiquid leg
  cannot be traded at the shown price.

Best call and best put ranking, model-ranked opportunity:
Both are buys. Candidates are liquid rows on the chosen expiry
with a positive premium, a delta, and an IV when the payoff
component is used. The score balances five measurable inputs,
weights fixed, no input fitted to the outcome:
- Payoff at the IV-implied expected move, weight 0.35:
  expected move is price times IV times sqrt(dte / 365).
  Payoff is the intrinsic value at price plus the move for a
  call, or price minus the move for a put, minus the premium,
  floored at a loss of the premium. Scored as the payoff
  multiple (payoff plus premium, divided by premium) capped
  at 3, divided by 3. A far out-of-the-money lottery strike
  cannot win on this alone, because its breakeven reach and
  delta scores pull it back, and the multiple is capped.
- Breakeven reach, weight 0.25: 1 divided by (1 plus
  breakeven distance as a percent divided by 5). A breakeven
  5% away scores 0.5, 10% away scores 0.33.
- Delta as a rough probability proxy, weight 0.15: 1 minus
  the distance of absolute delta from 0.45, divided by 0.45,
  floored at 0. Delta is labelled a rough proxy, never a
  guaranteed probability.
- Theta decay, weight 0.15: 1 divided by (1 plus 10 times
  daily theta as a percent of premium). Faster decay scores
  lower, because a buyer pays it every day.
- Liquidity, weight 0.10: half from spread (1 at 5% or less,
  falling to 0 at 15%) and half from open interest (open
  interest divided by 1000, capped at 1). Unknown spread or
  open interest scores 0.5 on that half, not 0 and not 1.
If IV is missing, the payoff component is dropped and the
remaining weights are renormalized, and the payload says IV
was missing, so the ranking is not presented as IV-based.
The selected play reports every ranking input, so the score
can be recomputed from the payload.

Straddle ranking:
Candidate straddles use the call and put at the same strike,
both bought, for strikes on the chosen expiry. Ranked on cost
versus the IV-implied expected move: expected move divided
by total cost, capped at 2, divided by 2 (weight 0.5), plus
breakeven reach from total cost as a percent of price
(weight 0.3, same 5% scale as above), plus liquidity of both
legs (weight 0.2). Theta and vega are shown, not scored,
because a straddle buyer wants movement, and theta is the
cost of waiting for it. Net Greeks: delta is call delta plus
put delta (put delta negative), gamma and vega are sums when
both legs carry them, otherwise Missing, theta decay per day
is the sum of both legs theta_seller.

Iron condor ranking:
Short out-of-the-money put and call plus long further
out-of-the-money wings, all on the chosen expiry, sold legs
priced at the bid, bought wings at ask else mid. Short
deltas must be between 0.15 and 0.35 absolute, long wing
deltas smaller than the short leg on the same side, and all
four legs liquid. Net credit must be positive. Max loss is
the larger wing width times 100 minus net credit. Ranked on
return on risk, net credit divided by max loss, capped at
0.5 and divided by 0.5 (weight 0.5), plus range, the mean
distance of the short strikes from price as a percent,
capped at 10% and divided by 10 (weight 0.3), plus liquidity
of all four legs (weight 0.2). Net Greeks follow sign
convention: short legs negate, long legs add. Gamma and
vega are Missing when any leg lacks them.
"""

import math


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _spread_pct(row):
    bid = _num(row.get("bid"))
    ask = _num(row.get("ask"))
    mid = _num(row.get("mid"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    base = mid if mid and mid > 0 else (bid + ask) / 2.0
    if not base:
        return None
    return (ask - bid) / base * 100.0


def _liquid(row):
    """Liquidity quality where known: spread at most 15%, OI at least 100."""
    spread = _spread_pct(row)
    if spread is not None and spread > 15.0:
        return False
    oi = _num(row.get("open_interest"))
    if oi is not None and oi < 100:
        return False
    return True


def _buy_premium(row):
    """Ask else mid, labelled, never a last trade. Returns (premium, source)."""
    ask = _num(row.get("ask"))
    mid = _num(row.get("mid"))
    if ask is not None and ask > 0:
        return ask, "ask"
    if mid is not None and mid > 0:
        return mid, "mid"
    return None, None


def _sell_premium(row):
    bid = _num(row.get("bid"))
    if bid is not None and bid > 0:
        return bid, "bid"
    return None, None


def _expected_move(price, iv_pct, dte):
    if iv_pct is None or dte is None or price is None:
        return None
    try:
        iv = float(iv_pct) / 100.0
        days = float(dte)
    except (TypeError, ValueError):
        return None
    if iv <= 0 or days <= 0:
        return None
    return price * iv * math.sqrt(days / 365.0)


def _liquidity_score(row):
    spread = _spread_pct(row)
    if spread is None:
        spread_score = 0.5
    elif spread <= 5.0:
        spread_score = 1.0
    elif spread >= 15.0:
        spread_score = 0.0
    else:
        spread_score = 1.0 - (spread - 5.0) / 10.0
    oi = _num(row.get("open_interest"))
    oi_score = 0.5 if oi is None else min(oi / 1000.0, 1.0)
    return round((spread_score + oi_score) / 2.0, 4)


def _sum_greek(rows, field, signs):
    values = []
    for row, sign in zip(rows, signs):
        value = _num(row.get(field))
        if value is None:
            return None
        values.append(sign * value)
    return round(sum(values), 4)


def _delta_signed(row, kind):
    delta = _num(row.get("delta"))
    if delta is None:
        delta_abs = _num(row.get("delta_abs"))
        if delta_abs is None:
            return None
        delta = delta_abs if kind == "call" else -delta_abs
    return delta


def _rank_long(row, price, kind, expected_move):
    """Score one long option. Returns (score, ranking_inputs) or None."""
    premium, source = _buy_premium(row)
    delta_abs = _num(row.get("delta_abs"))
    if premium is None or delta_abs is None:
        return None
    strike = _num(row.get("strike"))
    if strike is None or price is None or price <= 0:
        return None
    if kind == "call":
        breakeven = strike + premium
        target_price = price + expected_move if expected_move is not None else None
        payoff = (max(0.0, target_price - strike) - premium) if target_price is not None else None
    else:
        breakeven = strike - premium
        target_price = price - expected_move if expected_move is not None else None
        payoff = (max(0.0, strike - target_price) - premium) if target_price is not None else None
    breakeven_distance_pct = abs(breakeven - price) / price * 100.0
    reach = 1.0 / (1.0 + breakeven_distance_pct / 5.0)
    delta_score = max(0.0, 1.0 - abs(delta_abs - 0.45) / 0.45)
    theta = _num(row.get("theta_seller"))
    theta_pct = theta / premium if theta is not None and premium > 0 else None
    theta_score = 1.0 / (1.0 + 10.0 * theta_pct) if theta_pct is not None else 0.5
    liquidity = _liquidity_score(row)
    inputs = {
        "strike": strike,
        "premium_per_share": round(premium, 2),
        "premium_source": source,
        "premium_per_contract": round(premium * 100, 2),
        "breakeven": round(breakeven, 2),
        "breakeven_distance_pct": round(breakeven_distance_pct, 1),
        "delta_abs": round(delta_abs, 3),
        "delta_note": "Delta is a rough probability proxy, not a guaranteed probability.",
        "theta_seller_per_day": theta,
        "theta_pct_of_premium_per_day": round(theta_pct * 100, 2) if theta_pct is not None else None,
        "iv_pct": _num(row.get("iv_pct")),
        "expected_move": round(expected_move, 2) if expected_move is not None else None,
        "payoff_at_expected_move_per_contract": round(payoff * 100, 2) if payoff is not None else None,
        "spread_pct": round(_spread_pct(row), 1) if _spread_pct(row) is not None else None,
        "open_interest": row.get("open_interest"),
        "liquidity_score": liquidity,
        "max_loss_per_contract": round(premium * 100, 2),
    }
    if payoff is not None:
        payoff_multiple = min(max((payoff + premium) / premium, 0.0), 3.0) / 3.0
        score = (0.35 * payoff_multiple + 0.25 * reach + 0.15 * delta_score
                 + 0.15 * theta_score + 0.10 * liquidity)
        inputs["payoff_multiple_capped"] = round(min(max((payoff + premium) / premium, 0.0), 3.0), 2)
    else:
        score = (0.25 * reach + 0.15 * delta_score + 0.15 * theta_score
                 + 0.10 * liquidity) / 0.65
        inputs["payoff_multiple_capped"] = None
    inputs["score"] = round(score, 4)
    inputs["score_weights"] = (
        "Payoff at expected move 0.35, breakeven reach 0.25, delta "
        "proxy 0.15, theta decay 0.15, liquidity 0.10. IV missing "
        "drops the payoff component and renormalizes the rest."
    )
    return score, inputs


def _leg_summary(row, kind, premium, premium_source):
    return {
        "kind": kind,
        "strike": _num(row.get("strike")),
        "expiry": row.get("expiry"),
        "dte": row.get("dte"),
        "premium_per_share": round(premium, 2) if premium is not None else None,
        "premium_source": premium_source,
        "delta": _delta_signed(row, kind),
        "delta_abs": _num(row.get("delta_abs")),
        "gamma": _num(row.get("gamma")),
        "vega": _num(row.get("vega")),
        "theta_seller": _num(row.get("theta_seller")),
        "iv_pct": _num(row.get("iv_pct")),
        "bid": _num(row.get("bid")),
        "ask": _num(row.get("ask")),
        "mid": _num(row.get("mid")),
        "spread_pct": round(_spread_pct(row), 1) if _spread_pct(row) is not None else None,
        "open_interest": row.get("open_interest"),
    }


def build_option_strategies(price, puts, calls, chain_source=None, chain_error=None):
    """Build the strategies section from supplied chain rows."""
    puts = list(puts or [])
    calls = list(calls or [])
    base = {
        "available": False,
        "expiry": None,
        "dte": None,
        "expiry_rule": (
            "One expiry for all strategies: the listed expiry "
            "closest to 21 days to expiry, ties broken by the "
            "earliest expiry."
        ),
        "chain_source": chain_source,
        "selection_note": (
            "Model-ranked opportunity, not a prediction or a "
            "guarantee of profit. Ranking inputs are shown in "
            "details, so the reason a play ranked first can be "
            "checked. This section does not change the verdict "
            "put or call gating."
        ),
        "best_call": None,
        "best_put": None,
        "straddle": None,
        "iron_condor": None,
        "reason": None,
    }
    if price is None or price <= 0 or (not puts and not calls):
        base["reason"] = chain_error or "No listed options chain was available."
        return base
    expiries = {}
    for row in puts + calls:
        expiry = row.get("expiry")
        dte = _num(row.get("dte"))
        if expiry is None or dte is None:
            continue
        key = (abs(dte - 21.0), dte, str(expiry))
        if expiry not in expiries or key < expiries[expiry][0]:
            expiries[expiry] = (key, dte)
    if not expiries:
        base["reason"] = "No listed expiry with a days-to-expiry value was available."
        return base
    expiry, dte = min(expiries.items(), key=lambda kv: kv[1][0])[0], None
    expiry, dte = expiry, expiries[expiry][1]
    base["expiry"] = expiry
    base["dte"] = dte
    base["available"] = True
    exp_puts = [r for r in puts if r.get("expiry") == expiry and _liquid(r)]
    exp_calls = [r for r in calls if r.get("expiry") == expiry and _liquid(r)]

    # Best call and best put, both buys, ranked on opportunity.
    for kind, rows in (("call", exp_calls), ("put", exp_puts)):
        best = None
        for row in rows:
            expected = _expected_move(price, _num(row.get("iv_pct")), dte)
            ranked = _rank_long(row, price, kind, expected)
            if ranked is None:
                continue
            score, inputs = ranked
            if best is None or score > best[0]:
                best = (score, row, inputs)
        if best is None:
            base[f"best_{kind}"] = {
                "status": "unavailable",
                "reason": f"No liquid {kind} with a premium, delta, and price was available on {expiry}.",
            }
        else:
            _, row, inputs = best
            premium, source = _buy_premium(row)
            base[f"best_{kind}"] = {
                "status": "ok",
                "action": f"Buy the {kind}",
                "strike": _num(row.get("strike")),
                "expiry": expiry,
                "dte": dte,
                "premium_per_share": round(premium, 2),
                "premium_source": source,
                "premium_per_contract": round(premium * 100, 2),
                "breakeven": inputs["breakeven"],
                "max_loss_per_contract": inputs["max_loss_per_contract"],
                "key_greek": f"Delta {inputs['delta_abs']}",
                "ranking": inputs,
                "greeks": {
                    "delta": _delta_signed(row, kind),
                    "gamma": _num(row.get("gamma")),
                    "vega": _num(row.get("vega")),
                    "theta_seller": _num(row.get("theta_seller")),
                    "iv_pct": _num(row.get("iv_pct")),
                },
            }

    # Straddle: same strike call plus put, both bought.
    call_by_strike = {}
    for row in exp_calls:
        strike = _num(row.get("strike"))
        if strike is not None:
            call_by_strike.setdefault(strike, row)
    put_by_strike = {}
    for row in exp_puts:
        strike = _num(row.get("strike"))
        if strike is not None:
            put_by_strike.setdefault(strike, row)
    best_straddle = None
    for strike in sorted(set(call_by_strike) & set(put_by_strike)):
        call_row = call_by_strike[strike]
        put_row = put_by_strike[strike]
        call_premium, call_source = _buy_premium(call_row)
        put_premium, put_source = _buy_premium(put_row)
        if call_premium is None or put_premium is None:
            continue
        total = call_premium + put_premium
        ivs = [v for v in (_num(call_row.get("iv_pct")), _num(put_row.get("iv_pct"))) if v is not None]
        iv = sum(ivs) / len(ivs) if ivs else None
        expected = _expected_move(price, iv, dte)
        coverage = min(expected / total, 2.0) / 2.0 if expected is not None and total > 0 else None
        reach = 1.0 / (1.0 + (total / price * 100.0) / 5.0) if price else 0.0
        liquidity = (_liquidity_score(call_row) + _liquidity_score(put_row)) / 2.0
        if coverage is not None:
            score = 0.5 * coverage + 0.3 * reach + 0.2 * liquidity
        else:
            score = (0.3 * reach + 0.2 * liquidity) / 0.5
        if best_straddle is None or score > best_straddle[0]:
            best_straddle = (score, strike, call_row, put_row, call_premium,
                             put_premium, call_source, put_source, total,
                             iv, expected, coverage, reach, liquidity)
    if best_straddle is None:
        base["straddle"] = {
            "status": "unavailable",
            "reason": f"No strike on {expiry} had both a listed call and a listed put.",
        }
    else:
        (_, strike, call_row, put_row, call_premium, put_premium,
         call_source, put_source, total, iv, expected, coverage,
         reach, liquidity) = best_straddle
        base["straddle"] = {
            "status": "ok",
            "action": "Buy the straddle",
            "strike": strike,
            "expiry": expiry,
            "dte": dte,
            "total_cost_per_share": round(total, 2),
            "total_cost_per_contract": round(total * 100, 2),
            "lower_breakeven": round(strike - total, 2),
            "upper_breakeven": round(strike + total, 2),
            "key_greek": f"Vega {(_num(call_row.get('vega')) + _num(put_row.get('vega')) if _num(call_row.get('vega')) is not None and _num(put_row.get('vega')) is not None else 'Missing')}",
            "greeks": {
                "delta": (_delta_signed(call_row, "call") + _delta_signed(put_row, "put"))
                if _delta_signed(call_row, "call") is not None and _delta_signed(put_row, "put") is not None else None,
                "gamma": _sum_greek([call_row, put_row], "gamma", [1, 1]),
                "vega": _sum_greek([call_row, put_row], "vega", [1, 1]),
                "theta_seller": _sum_greek([call_row, put_row], "theta_seller", [1, 1]),
                "iv_pct": iv,
            },
            "ranking": {
                "score": round(best_straddle[0], 4),
                "score_weights": (
                    "Expected move divided by cost, capped at 2, "
                    "weight 0.5; breakeven reach weight 0.3; "
                    "liquidity of both legs weight 0.2. IV missing "
                    "drops the coverage component and renormalizes."
                ),
                "total_cost_per_share": round(total, 2),
                "expected_move": round(expected, 2) if expected is not None else None,
                "expected_move_divided_by_cost": round(expected / total, 2) if expected is not None and total > 0 else None,
                "breakeven_reach": round(reach, 4),
                "liquidity_score": round(liquidity, 4),
                "call_premium_source": call_source,
                "put_premium_source": put_source,
                "legs": [
                    _leg_summary(call_row, "call", call_premium, call_source),
                    _leg_summary(put_row, "put", put_premium, put_source),
                ],
            },
        }

    # Iron condor: short OTM put and call, long further OTM wings.
    sorted_puts = sorted(exp_puts, key=lambda r: _num(r.get("strike")) or 0)
    sorted_calls = sorted(exp_calls, key=lambda r: _num(r.get("strike")) or 0)
    best_condor = None
    for short_put in sorted_puts:
        short_put_strike = _num(short_put.get("strike"))
        short_put_delta = _num(short_put.get("delta_abs"))
        if short_put_strike is None or short_put_strike >= price:
            continue
        if short_put_delta is None or not (0.15 <= short_put_delta <= 0.35):
            continue
        short_put_premium, _ = _sell_premium(short_put)
        if short_put_premium is None:
            continue
        wings_put = [r for r in sorted_puts if _num(r.get("strike")) is not None
                     and _num(r.get("strike")) < short_put_strike
                     and (_num(r.get("delta_abs")) is None or _num(r.get("delta_abs")) < short_put_delta)]
        for short_call in sorted_calls:
            short_call_strike = _num(short_call.get("strike"))
            short_call_delta = _num(short_call.get("delta_abs"))
            if short_call_strike is None or short_call_strike <= price:
                continue
            if short_call_delta is None or not (0.15 <= short_call_delta <= 0.35):
                continue
            short_call_premium, _ = _sell_premium(short_call)
            if short_call_premium is None:
                continue
            wings_call = [r for r in sorted_calls if _num(r.get("strike")) is not None
                          and _num(r.get("strike")) > short_call_strike
                          and (_num(r.get("delta_abs")) is None or _num(r.get("delta_abs")) < short_call_delta)]
            for long_put in wings_put:
                long_put_premium, long_put_source = _buy_premium(long_put)
                if long_put_premium is None:
                    continue
                for long_call in wings_call:
                    long_call_premium, long_call_source = _buy_premium(long_call)
                    if long_call_premium is None:
                        continue
                    credit = short_put_premium + short_call_premium - long_put_premium - long_call_premium
                    if credit <= 0:
                        continue
                    put_width = short_put_strike - _num(long_put.get("strike"))
                    call_width = _num(long_call.get("strike")) - short_call_strike
                    max_loss = max(put_width, call_width) * 100 - credit * 100
                    if max_loss <= 0:
                        continue
                    ror = credit * 100 / max_loss
                    range_pct = ((price - short_put_strike) + (short_call_strike - price)) / 2.0 / price * 100.0
                    range_score = min(range_pct, 10.0) / 10.0
                    liquidity = sum(_liquidity_score(r) for r in (short_put, short_call, long_put, long_call)) / 4.0
                    score = 0.5 * (min(ror, 0.5) / 0.5) + 0.3 * range_score + 0.2 * liquidity
                    if best_condor is None or score > best_condor[0]:
                        best_condor = (score, short_put, short_call, long_put, long_call,
                                       credit, max_loss, ror, put_width, call_width,
                                       range_pct, liquidity, short_put_premium,
                                       short_call_premium, long_put_premium,
                                       long_call_premium, long_put_source, long_call_source)
    if best_condor is None:
        base["iron_condor"] = {
            "status": "unavailable",
            "reason": (
                f"No iron condor on {expiry} had liquid short legs "
                "with deltas 0.15 to 0.35, further out-of-the-money "
                "wings, and a positive net credit."
            ),
        }
    else:
        (_, short_put, short_call, long_put, long_call, credit, max_loss,
         ror, put_width, call_width, range_pct, liquidity,
         short_put_premium, short_call_premium, long_put_premium,
         long_call_premium, long_put_source, long_call_source) = best_condor
        short_put_strike = _num(short_put.get("strike"))
        short_call_strike = _num(short_call.get("strike"))
        legs = [
            _leg_summary(short_put, "put", short_put_premium, "bid"),
            _leg_summary(long_put, "put", long_put_premium, long_put_source),
            _leg_summary(short_call, "call", short_call_premium, "bid"),
            _leg_summary(long_call, "call", long_call_premium, long_call_source),
        ]
        # Net Greeks with sign convention: short legs negate, long legs add.
        # Delta signs: short put +abs, long put -abs, short call -abs, long call +abs.
        def _signed_delta(row, kind, sign):
            d = _delta_signed(row, kind)
            return sign * d if d is not None else None

        deltas = [_signed_delta(short_put, "put", 1), _signed_delta(long_put, "put", -1),
                  _signed_delta(short_call, "call", -1), _signed_delta(long_call, "call", 1)]
        net_delta = round(sum(deltas), 4) if all(d is not None for d in deltas) else None
        base["iron_condor"] = {
            "status": "ok",
            "action": "Sell the iron condor",
            "expiry": expiry,
            "dte": dte,
            "short_put_strike": short_put_strike,
            "long_put_strike": _num(long_put.get("strike")),
            "short_call_strike": short_call_strike,
            "long_call_strike": _num(long_call.get("strike")),
            "put_width": put_width,
            "call_width": call_width,
            "net_credit_per_share": round(credit, 2),
            "net_credit_per_contract": round(credit * 100, 2),
            "max_loss_per_contract": round(max_loss, 2),
            "return_on_risk_pct": round(ror * 100, 1),
            "lower_breakeven": round(short_put_strike - credit, 2),
            "upper_breakeven": round(short_call_strike + credit, 2),
            "key_greek": f"Return on risk {round(ror * 100, 1)}%",
            "greeks": {
                "delta": net_delta,
                "gamma": _sum_greek([short_put, long_put, short_call, long_call], "gamma", [-1, 1, -1, 1]),
                "vega": _sum_greek([short_put, long_put, short_call, long_call], "vega", [-1, 1, -1, 1]),
                "theta_seller": _sum_greek([short_put, long_put, short_call, long_call], "theta_seller", [1, -1, 1, -1]),
                "iv_pct": None,
            },
            "ranking": {
                "score": round(best_condor[0], 4),
                "score_weights": (
                    "Return on risk, capped at 50%, weight 0.5; "
                    "short-strike range as a percent of price, "
                    "capped at 10%, weight 0.3; liquidity of all "
                    "four legs weight 0.2."
                ),
                "net_credit_per_contract": round(credit * 100, 2),
                "max_loss_per_contract": round(max_loss, 2),
                "return_on_risk_pct": round(ror * 100, 1),
                "short_put_delta_abs": _num(short_put.get("delta_abs")),
                "short_call_delta_abs": _num(short_call.get("delta_abs")),
                "range_pct": round(range_pct, 1),
                "liquidity_score": round(liquidity, 4),
                "legs": legs,
            },
        }
    return base
