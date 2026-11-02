"""Additional DCF methods for the ticker lookup long-term lane.

Context only. These methods never change the long-term verdict,
the DCA decision, or put and call gating. The statements anchor
in longterm_valuation.build_longterm stays the verdict driver;
the methods here explain what a different, stated set of
assumptions would say about the same company.

Method 1, forward growth scenarios:
Scenario rules, fixed, never fitted to the current price. The
price is not an input to any scenario below, only to the final
fair value division and to upside percentages.
- Let g be the 3-year revenue CAGR (fraction) and m the current
  FCF margin (fraction).
- Bear: growth starts at half of g, floored at 2% and capped at
  10% for years 1 to 5, then 3%; margin stays near current at
  0.90 times m; terminal growth 2%.
- Base: growth starts at 1.25 times g, floored at 5% and capped
  at 25% for years 1 to 5, then 5%; margin expands to 1.25 times
  m, capped at 35%; terminal growth 2.5%.
- Bull: growth starts at 1.75 times g, floored at 10% and capped
  at 35% for years 1 to 5, then 8%; margin expands to 1.50 times
  m, capped at 40%; terminal growth 3%.
Growth fades inside the shared engine from the years 1 to 5 rate
to the years 6 to 10 rate, stepwise, exactly as the anchor does.

Method 3, normalized cash flows plus live WACC:
- When a multi-year history is supplied (most recent first, in
  millions), normalized revenue is the mean of up to the last
  3 valid years and normalized FCF margin is total FCF divided
  by total revenue over those years. Scenarios reuse the anchor
  scenario rule on the normalized growth and margin.
- When no history is supplied but a verified 3-year average FCF
  margin is available from quality, the normalized margin is
  that average and revenue stays the latest year, because
  revenue averaging is not available from snapshot inputs.
  That limit is stated in the payload, not hidden.
- WACC is the anchor WACC: live when a live 10-year yield was
  supplied to build_longterm, otherwise the labelled hardcoded
  4.5% fallback. This module does not invent a yield.

Method 2, sum of parts, lives in the same payload:
- Segments are valued only when the caller supplies segment
  revenue and FCF from a wired source. No wired source in this
  codebase (Polygon SEC, yfinance annuals, Finnhub profile and
  basics as used here) provides a segment split, so live runs
  read as unavailable, with the reason named, never a split
  allocated by guess from total revenue.
- A future-business upside line (robotaxi, AI, or similar) is
  shown only when the caller supplies it explicitly with a
  source. It is never added to the operating total, never used
  for the verdict or DCA, and its combined total is never
  computed as one blended number.
"""

import math


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, value))


def _round2(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def forward_scenarios(rev_growth, fcf_margin):
    """Fixed forward scenario rules, documented in the module docstring."""
    g = float(rev_growth)
    m = float(fcf_margin)
    return {
        "bear": {
            "g1": _clamp(g * 0.50, 0.02, 0.10), "g2": 0.03,
            "fm": max(m * 0.90, 0.01), "tg": 0.02,
        },
        "base": {
            "g1": _clamp(g * 1.25, 0.05, 0.25), "g2": 0.05,
            "fm": min(m * 1.25, 0.35), "tg": 0.025,
        },
        "bull": {
            "g1": _clamp(g * 1.75, 0.10, 0.35), "g2": 0.08,
            "fm": min(m * 1.50, 0.40), "tg": 0.03,
        },
    }


def _fair_values(revenue, dr, scenarios, market_cap, shares, price):
    """Run the shared engine and return fair values and upsides, or None."""
    try:
        from services.discovery_engine import _run_dcf
    except Exception:
        return None
    try:
        out = _run_dcf(float(revenue), 0.0, float(dr), scenarios, float(market_cap))
    except Exception:
        return None
    fair = {}
    upside = {}
    for name in ("bear", "base", "bull"):
        pv = out.get(name)
        if pv is None or shares <= 0:
            return None
        fair[name] = round(pv / shares, 2)
        upside[name] = round((fair[name] - price) / price * 100, 1) if price else None
    return {"fair_value": fair, "upside_pct": upside}


def _scenario_lines(scenarios):
    return {
        name: {
            "g1_pct": round(s["g1"] * 100, 1),
            "g2_pct": round(s["g2"] * 100, 1),
            "fcf_margin_pct": round(s["fm"] * 100, 1),
            "terminal_growth_pct": round(s["tg"] * 100, 1),
        }
        for name, s in scenarios.items()
    }


def build_forward_method(price, revenue, fcf_margin, rev_growth, dr,
                         market_cap, shares):
    """Forward scenarios method, or a missing payload when inputs fail."""
    if revenue is None or revenue <= 0 or shares is None or shares <= 0:
        return {
            "status": "missing", "fair_value": None, "upside_pct": None,
            "scenarios": None, "framing": None,
            "assumptions": None,
            "reason": "Forward scenarios need reported revenue and shares.",
        }
    scenarios = forward_scenarios(rev_growth, fcf_margin)
    result = _fair_values(revenue, dr, scenarios, market_cap, shares, price)
    if result is None or dr <= scenarios["base"]["tg"]:
        return {
            "status": "missing", "fair_value": None, "upside_pct": None,
            "scenarios": _scenario_lines(scenarios), "framing": None,
            "assumptions": None,
            "reason": "Forward scenarios could not be computed with this WACC.",
        }
    base = result["fair_value"]["base"]
    return {
        "status": "ok",
        "fair_value": result["fair_value"],
        "upside_pct": result["upside_pct"],
        "scenarios": _scenario_lines(scenarios),
        "framing": (
            f"Forward scenarios say ${base} in the base case, on faster "
            "growth and expanding margins. This is context, not a "
            "price target, and it does not change the verdict."
        ),
        "assumptions": (
            "Growth starts near the 3-year revenue CAGR: bear half of "
            "it (2% to 10%), base 1.25 times it (5% to 25%), bull 1.75 "
            "times it (10% to 35%), fading to 3%, 5%, and 8% in years "
            "6 to 10. Margins: bear 0.90 times current, base 1.25 "
            "times current capped at 35%, bull 1.50 times current "
            "capped at 40%. Terminal growth 2%, 2.5%, 3%. Same WACC "
            "as the statements anchor. No input is fitted to the "
            "current price."
        ),
        "reason": None,
    }


def _normalized_inputs(history, quality_avg_margin_pct, revenue, rev_growth):
    """Return (norm_revenue, norm_margin, norm_growth, source, note).

    history is most recent first, in millions, with revenue and
    fcf keys. Quality average margin is a percentage.
    """
    valid = []
    if isinstance(history, list):
        for row in history[:3]:
            if not isinstance(row, dict):
                continue
            try:
                rev = float(row.get("revenue"))
                fcf = float(row.get("fcf"))
            except (TypeError, ValueError):
                continue
            if rev > 0:
                valid.append((rev, fcf))
    if len(valid) >= 2:
        total_rev = sum(r for r, _ in valid)
        total_fcf = sum(f for _, f in valid)
        norm_revenue = total_rev / len(valid)
        norm_margin = total_fcf / total_rev if total_rev else None
        if norm_margin is not None and norm_margin > 0:
            newest = valid[0][0]
            oldest = valid[-1][0]
            years = len(valid) - 1
            if oldest > 0 and years >= 1:
                norm_growth = (newest / oldest) ** (1.0 / years) - 1.0
            else:
                norm_growth = rev_growth
            return (
                norm_revenue, norm_margin, norm_growth,
                "history_3y_average",
                f"Revenue and FCF averaged over {len(valid)} years "
                "from the supplied history.",
            )
    if quality_avg_margin_pct is not None:
        try:
            margin = float(quality_avg_margin_pct) / 100.0
        except (TypeError, ValueError):
            margin = None
        if margin is not None and margin > 0:
            return (
                revenue, margin, rev_growth,
                "quality_3y_average_margin_latest_revenue",
                "FCF margin is the verified 3-year average. Revenue "
                "stays the latest year, because revenue averaging "
                "is not available from snapshot inputs.",
            )
    return None, None, None, None, None


def build_normalized_method(price, revenue, fcf_margin, rev_growth, dr,
                            market_cap, shares, history,
                            quality_avg_margin_pct, wacc_pct,
                            risk_free_source):
    """Normalized method, or a missing payload when no average exists."""
    norm_revenue, norm_margin, norm_growth, source, note = _normalized_inputs(
        history, quality_avg_margin_pct, revenue, rev_growth)
    if norm_revenue is None or norm_margin is None:
        return {
            "status": "missing", "fair_value": None, "upside_pct": None,
            "scenarios": None, "framing": None, "assumptions": None,
            "source": None, "note": None, "wacc_pct": wacc_pct,
            "risk_free_source": risk_free_source,
            "reason": (
                "Normalized DCF needs a multi-year history or a "
                "verified 3-year average FCF margin, and neither "
                "was available."
            ),
        }
    # Anchor scenario rule, applied to normalized inputs, so the
    # normalized method differs only by its inputs, not by a new rule.
    from services.longterm_valuation import _scenarios

    scenarios = _scenarios(norm_growth, norm_margin)
    result = _fair_values(norm_revenue, dr, scenarios, market_cap, shares, price)
    if result is None or dr <= scenarios["base"]["tg"]:
        return {
            "status": "missing", "fair_value": None, "upside_pct": None,
            "scenarios": _scenario_lines(scenarios), "framing": None,
            "assumptions": None, "source": source, "note": note,
            "wacc_pct": wacc_pct, "risk_free_source": risk_free_source,
            "reason": "Normalized DCF could not be computed with this WACC.",
        }
    base = result["fair_value"]["base"]
    return {
        "status": "ok",
        "fair_value": result["fair_value"],
        "upside_pct": result["upside_pct"],
        "scenarios": _scenario_lines(scenarios),
        "framing": (
            f"Normalized cash flows say ${base} in the base case, "
            "smoothing out a single depressed year. This is "
            "context, not a price target."
        ),
        "assumptions": note + " Scenarios use the anchor rule on "
        "the normalized inputs. WACC " + str(wacc_pct) + "% "
        "(risk free source: " + str(risk_free_source) + ").",
        "source": source, "note": note, "wacc_pct": wacc_pct,
        "risk_free_source": risk_free_source,
        "normalized_revenue_millions": round(norm_revenue, 1),
        "normalized_fcf_margin_pct": round(norm_margin * 100, 1),
        "normalized_growth_pct": round(norm_growth * 100, 1),
        "reason": None,
    }


def build_sotp_method(price, dr, shares, rev_growth, segments, future_upside):
    """Sum of parts, operating total separate from future upside.

    segments is a list of {name, revenue, fcf} in millions, or
    None. future_upside is a dict {per_share, source, note} only
    when explicitly supplied, otherwise None. Nothing is ever
    blended: combined_total is always None.
    """
    upside = {
        "status": "missing", "per_share": None, "source": None,
        "note": (
            "Future businesses such as robotaxi or AI are not "
            "valued here, because no wired source supplies their "
            "revenue or cash flow. They are not added to the "
            "operating total."
        ),
    }
    if isinstance(future_upside, dict) and future_upside.get("per_share") is not None:
        upside = {
            "status": "supplied", "per_share": _round2(future_upside.get("per_share")),
            "source": future_upside.get("source"),
            "note": future_upside.get("note") or (
                "Supplied upside, kept separate from the operating "
                "total and never used for the verdict or DCA."
            ),
        }
    if not segments:
        return {
            "status": "unavailable", "fair_value": None, "upside_pct": None,
            "segments": [], "operating_total_millions": None,
            "upside": upside, "combined_total": None,
            "framing": None,
            "reason": (
                "No segment revenue and free cash flow from a "
                "wired source, so no segment split is shown."
            ),
        }
    from services.longterm_valuation import _scenarios

    segment_rows = []
    totals = {"bear": 0.0, "base": 0.0, "bull": 0.0}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            seg_rev = float(seg.get("revenue"))
            seg_fcf = float(seg.get("fcf"))
        except (TypeError, ValueError):
            continue
        if seg_rev <= 0 or seg_fcf <= 0:
            continue
        seg_margin = seg_fcf / seg_rev
        scenarios = _scenarios(rev_growth, seg_margin)
        try:
            from services.discovery_engine import _run_dcf

            # Market cap is only used by the shared engine for an
            # upside percentage, which sum of parts ignores. Pass
            # segment revenue so the engine never divides by zero.
            out = _run_dcf(seg_rev, seg_margin, dr, scenarios, seg_rev)
        except Exception:
            continue
        row = {"name": seg.get("name"), "revenue_millions": seg_rev,
               "fcf_millions": seg_fcf,
               "fair_value_millions": {n: out.get(n) for n in ("bear", "base", "bull")}}
        segment_rows.append(row)
        for name in totals:
            totals[name] += out.get(name) or 0.0
    if not segment_rows or shares <= 0:
        return {
            "status": "unavailable", "fair_value": None, "upside_pct": None,
            "segments": segment_rows, "operating_total_millions": None,
            "upside": upside, "combined_total": None,
            "framing": None,
            "reason": (
                "Segment data was supplied but could not be valued, "
                "so no segment total is shown."
            ),
        }
    fair = {name: round(totals[name] / shares, 2) for name in totals}
    upside_pct = {
        name: round((fair[name] - price) / price * 100, 1) if price else None
        for name in totals
    }
    return {
        "status": "ok", "fair_value": fair, "upside_pct": upside_pct,
        "segments": segment_rows,
        "operating_total_millions": {n: round(v, 1) for n, v in totals.items()},
        "upside": upside, "combined_total": None,
        "framing": (
            "Sum of parts operating total is the segment DCFs "
            "added together. Future upside, if any, is a separate "
            "line below, never blended into this total."
        ),
        "reason": None,
    }


def build_dcf_methods(price, revenue, fcf, shares, rev_growth, fcf_margin,
                      dr, market_cap, quality, statements, wacc=None):
    """Build all three additional methods for one computed anchor DCF."""
    statements = statements or {}
    quality = quality or {}
    wacc = wacc or {}
    wacc_pct = wacc.get("wacc_pct")
    risk_free_source = wacc.get("risk_free_source")
    forward = build_forward_method(price, revenue, fcf_margin, rev_growth,
                                   dr, market_cap, shares)
    normalized = build_normalized_method(
        price, revenue, fcf_margin, rev_growth, dr, market_cap, shares,
        statements.get("history"), quality.get("fcf_margin_avg_3y_pct"),
        wacc_pct, risk_free_source)
    sotp = build_sotp_method(price, dr, shares, rev_growth,
                             statements.get("segments"),
                             statements.get("future_upside"))
    return {
        "forward": forward,
        "normalized": normalized,
        "sum_of_parts": sotp,
        "note": (
            "Context only. These methods do not change the "
            "long-term verdict, the DCA decision, or put and call "
            "gating. The statements anchor above stays the verdict "
            "driver."
        ),
    }


def fetch_live_10y_yield():
    """Best-effort live 10-year Treasury yield from yfinance ^TNX.

    Returns a fraction (for example 0.049 for 4.9%), or None when
    yfinance is unavailable or returns no price. Never raises.
    ^TNX is quoted in percent, so the quoted price is divided
    by 100. This is a wired-source type already used in this
    codebase (yfinance for prices and chains), not a new data
    vendor. Callers must label a None result as the fallback,
    exactly as the anchor WACC already does.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker("^TNX")
        price = None
        try:
            price = getattr(ticker.fast_info, "last_price", None)
        except Exception:
            price = None
        if price is None:
            try:
                hist = ticker.history(period="5d")
                if hist is not None and len(hist) > 0:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                price = None
        if price is None:
            return None
        value = float(price) / 100.0
        if not (0.0 < value < 0.20):
            return None
        return value
    except Exception:
        return None
