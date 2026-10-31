"""
Long-term lane for the ticker lookup, separate from the timing verdict.

The timing verdict (BUY NOW / WAIT FOR ENTRY / AVOID / CANNOT JUDGE)
answers "should I trade this now?" The long-term lane answers a
different question: "is this a strong company, and is it undervalued
on a 3 to 5 year view?" A timing AVOID must never read as "never buy
this company", so the two lanes are computed independently and the
long-term lane never changes put or call gating.

Calculation core, reused, not a new model:
- Present value engine: services.discovery_engine._run_dcf (10 years
  of FCF plus a Gordon Growth terminal value). Growth fades in that
  core from g1 in years 1 to 5 to g2 in years 6 to 10, a stepwise
  fade, not a flat extrapolation. Scenario FCF margins differ from
  the current margin (bull up to 20% higher, capped, bear 25 to 30%
  lower), which is the margin drift in this core. A per-year linear
  fade and per-year margin drift are NOT in _run_dcf, and this
  module does not claim them.
- Scenario caps: the same caps as services.dcf_service._mechanial_scenarios,
  with one deliberate fix: that function floors FCF margin at
  max(fcf_margin, net_margin * 0.85, gross_margin * 0.15), which
  hides a negative FCF margin. This module never floors. A negative
  reported FCF margin is BLOCKED, not replaced by a proxy.
- WACC: the same CAPM formula as discovery_engine._wacc_from_beta
  (cost of equity, debt blend for non-financials with debt to equity
  above 0.5, sector floors, clamped to the sector floor through 15%),
  with the risk-free rate as an explicit input. When no live 10-year
  yield is supplied, the fallback is the hardcoded 4.5% from the
  existing core, and the payload says so plainly in
  risk_free_source. No live 10-year yield source exists in this repo
  yet, so live lookups currently report the fallback, never a
  guessed yield.
- Reverse DCF: services.discovery_engine._reverse_dcf, the growth
  rate the market is already pricing in.
- WACC sensitivity: the same _run_dcf engine at 5.5%, 7.0%, and
  8.5%, computed here rather than imported from dcf_service,
  because dcf_service imports the Finnhub client at module level
  and that import is unavailable in a sandbox without the finnhub
  package. The rates and the engine are identical, not a new model.

Real statements, not a price echo:
- The DCF needs reported revenue and reported free cash flow, in
  the same units (millions), plus shares outstanding in millions.
  Revenue derived from market cap divided by P/S is NOT used here,
  because that derivation is not a statement input and can silently
  track the price. When no statements are supplied, the DCF is
  BLOCKED with reason missing_statements (when quality is verified)
  or the lane is NOT VERIFIED (when quality is also absent). The
  live lookup path currently supplies no statements, because this
  repo has no validated financial-statements parser (Finnhub
  basic financials gives ratios, not statements), so live DCF
  values are BLOCKED until a validated statements source is wired.
  That is the honest state of this branch, not a live proof claim.

Verdict rules, deterministic:
- bear fair value above price: strong, margin_of_safety.
- base above price, bear below: strong, undervalued_central_case,
  unless quality composite below 50 caps it to watch.
- only bull above price: watch, fairly_valued.
- all three below price: weak, overvalued, even if quality is high.
- blocked: DCF cannot be computed honestly (negative FCF, missing
  statements, financial sector where a revenue DCF does not fit,
  invalid inputs, or a WACC that cannot discount a terminal value).
- not_verified: quality is not in the screener snapshot and no DCF
  can be computed, so nothing is invented about the company.

Bridge line: when the verdict is strong and base fair value is
above price, the lane says "Long-term buy candidate, wait for
entry" and points to the WAIT entry plan prices. It does NOT unlock
a weekly put or call. Options stay gated exactly as they are.
"""
import logging

logger = logging.getLogger(__name__)

_FALLBACK_RISK_FREE = 0.045
_FALLBACK_ERP = 0.055
_QUALITY_STRONG_CAP = 50.0
_EXIT_DISAGREEMENT_PCT = 25.0

_FINANCIAL_SECTORS = {
    "Banking", "Banks", "Insurance",
    "Financial Services", "Capital Markets",
    "Diversified Financial Services",
    "Consumer Finance", "Mortgage Finance",
}


def _money(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _pct(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _pct1(value):
    """Round a displayed percentage to one decimal place.

    Snapshot files carry full float precision (for example ROIC
    102.387442503643). Displaying that precision is noise, so
    every percentage the long-term lane reports is rounded to
    one decimal at the source, not only in the frontend.
    """
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def wacc_with_risk_free(beta, risk_free_rate, erp, debt_equity, sector):
    """CAPM WACC, same formula as discovery_engine._wacc_from_beta.

    Only the risk-free rate is substituted. Sector floors and the
    15% cap come from discovery_engine, so this is not a second
    WACC model.
    """
    from services.discovery_engine import _SECTOR_WACC_FLOORS, _DEFAULT_WACC_FLOOR

    rf = _FALLBACK_RISK_FREE if risk_free_rate is None else float(risk_free_rate)
    erp = _FALLBACK_ERP if erp is None else float(erp)
    beta = 1.0 if beta is None else float(beta)
    cost_of_equity = rf + beta * erp
    is_financial = sector in _FINANCIAL_SECTORS
    if debt_equity and float(debt_equity) > 0.5 and not is_financial:
        weight_equity = 1 / (1 + float(debt_equity))
        weight_debt = float(debt_equity) / (1 + float(debt_equity))
        cost_of_debt = 0.04
        tax_rate = 0.21
        wacc = (weight_equity * cost_of_equity
                + weight_debt * cost_of_debt * (1 - tax_rate))
    else:
        wacc = cost_of_equity
    floor = _SECTOR_WACC_FLOORS.get(sector, _DEFAULT_WACC_FLOOR)
    return max(floor, min(wacc, 0.15))


def _scenarios(rev_growth, fcf_margin):
    """Bear, base, and bull scenarios, same caps as dcf_service.

    rev_growth and fcf_margin are fractions. No FCF floor: the
    caller blocks negative FCF before this runs, so a margin here
    is always the reported margin, scaled per scenario.
    """
    if rev_growth > 0.20:
        return {
            "bull": {"g1": min(rev_growth * 0.70, 0.30), "g2": 0.12,
                     "fm": min(fcf_margin * 1.20, 0.45), "tg": 0.035},
            "base": {"g1": min(rev_growth * 0.45, 0.18), "g2": 0.08,
                     "fm": fcf_margin, "tg": 0.030},
            "bear": {"g1": min(max(rev_growth * 0.15, 0.02), 0.10), "g2": 0.04,
                     "fm": fcf_margin * 0.70, "tg": 0.020},
        }
    bull_g1 = min(rev_growth * 1.3, 0.20)
    base_g1 = min(rev_growth * 0.80, min(bull_g1, 0.12))
    bear_g1 = min(max(rev_growth * 0.30, 0.02), base_g1)
    return {
        "bull": {"g1": bull_g1, "g2": 0.08,
                 "fm": min(fcf_margin * 1.20, 0.45), "tg": 0.030},
        "base": {"g1": base_g1, "g2": 0.05,
                 "fm": fcf_margin, "tg": 0.025},
        "bear": {"g1": bear_g1, "g2": 0.03,
                 "fm": max(fcf_margin * 0.75, 0.01), "tg": 0.020},
    }


def _wacc_sensitivity(revenue_0, fcf_0, scenarios, market_cap, shares_m,
                      current_price):
    """DCF at fixed WACC levels, same _run_dcf engine, same rates.

    Mirrors dcf_service._wacc_sensitivity without importing that
    module, for the sandbox import reason in the module docstring.
    """
    from services.discovery_engine import _run_dcf

    rows = []
    for test_dr in (0.055, 0.070, 0.085):
        sens = _run_dcf(revenue_0, fcf_0, test_dr, scenarios, market_cap)
        row = {"wacc_pct": round(test_dr * 100, 1)}
        for name in ("bull", "base", "bear"):
            up = sens.get(f"{name}_upside")
            price = (
                round(current_price * (1 + up / 100), 2)
                if (current_price and up is not None and shares_m > 0)
                else None
            )
            row[name] = {"price": price, "upside": up}
        rows.append(row)
    return rows


def _quality_from_snapshot(snapshot_entry):
    """Quality from the dated screener snapshot, or not verified.

    snapshot_entry is the dict returned by ticker_lookup
    _fundamentals_for: status verified with the snapshot fields, or
    status not_verified. Only fields actually in the snapshot file
    are reported. Quality and consistency scores are not in that
    file, so they are never invented here.
    """
    if not isinstance(snapshot_entry, dict):
        snapshot_entry = {}
    if snapshot_entry.get("status") != "verified":
        return {
            "status": "not_verified",
            "run_date": None,
            "source": "quality_screener_v2",
            "note": (
                "This ticker is not in the 2026-10-26 quality screener "
                "v2 survivors, so no quality is verified here."
            ),
        }
    return {
        "status": "verified",
        "run_date": snapshot_entry.get("run_date"),
        "source": "quality_screener_v2",
        "composite": _pct1(snapshot_entry.get("composite")),
        "label": snapshot_entry.get("label"),
        "rev_cagr_3y_pct": _pct1(snapshot_entry.get("rev_cagr_3y_pct")),
        "fcf_margin_avg_3y_pct": _pct1(snapshot_entry.get("fcf_margin_avg_3y_pct")),
        "roic_pct": _pct1(snapshot_entry.get("roic_pct")),
        "operating_margin_pct": _pct1(snapshot_entry.get("operating_margin_pct")),
        "ev_to_ebitda": snapshot_entry.get("ev_to_ebitda"),
        "fcf_yield_pct": _pct1(snapshot_entry.get("fcf_yield_pct")),
        "smoothed_rule_of_40": _pct1(snapshot_entry.get("smoothed_rule_of_40")),
        "note": (
            "Quality from the dated screener snapshot, not a live "
            "recalculation. A snapshot does not prove current quality."
        ),
    }


def _blocked(quality, reason_code, reason, **extra):
    lane = {
        "verdict": "blocked",
        "label": "BLOCKED",
        "reason": reason,
        "reason_code": reason_code,
        "quality": quality,
        "dcf": None,
        "wacc": None,
        "bridge_line": None,
        "bridge_entry": None,
        # Notes are kept empty here on purpose: the frontend
        # already prints reason once, and printing the same text
        # again as a note is what duplicated the BLOCKED text.
        "notes": [],
    }
    lane.update(extra)
    return lane


def _not_verified(quality, reason=None):
    return {
        "verdict": "not_verified",
        "label": "NOT VERIFIED",
        "reason": reason or (
            "Quality is not in the screener snapshot and no DCF can "
            "be computed, so no long-term verdict is claimed."
        ),
        "reason_code": "not_verified",
        "quality": quality,
        "dcf": None,
        "wacc": None,
        "bridge_line": None,
        "bridge_entry": None,
        "notes": [
            "No quality and no DCF, so nothing about this company "
            "is invented for the long-term lane.",
        ],
    }


def build_longterm(ticker, price, snapshot_entry, statements=None,
                   risk_free_rate=None, erp=None):
    """Build the long-term lane for one ticker.

    statements, when given, is a dict with reported values in
    millions (revenue, fcf, shares_outstanding) plus optional
    beta, sector, industry, debt_equity, revenue_growth_pct,
    operating_margin_pct, ev_to_ebitda. Units must match: market
    cap is price times shares_outstanding, in millions, the same
    convention as dcf_service. No statements means no DCF, never
    a market-cap divided by P/S fallback.
    """
    quality = _quality_from_snapshot(snapshot_entry)
    quality_verified = quality["status"] == "verified"

    if statements is None:
        if quality_verified:
            return _blocked(
                quality, "missing_statements",
                "Quality is verified in the snapshot, but no reported "
                "revenue and free cash flow were supplied, so no DCF "
                "fair value is computed. Revenue derived from market "
                "cap divided by P/S is not used here. This is not a "
                "weekend or market-closed issue. It will be blocked "
                "on a weekday too, until a statements source is wired.",
            )
        return _not_verified(quality)

    sector = statements.get("sector") or statements.get("industry")
    if sector in _FINANCIAL_SECTORS:
        return _blocked(
            quality, "financial_sector",
            "A revenue-based DCF does not fit a financial company, "
            "so no DCF fair value is computed for this sector.",
        )

    revenue = statements.get("revenue")
    fcf = statements.get("fcf")
    shares = statements.get("shares_outstanding")
    if revenue is None or fcf is None or shares is None:
        return _blocked(
            quality, "missing_statements",
            "Reported revenue, free cash flow, or shares outstanding "
            "is missing, so no DCF fair value is computed.",
        )
    try:
        revenue = float(revenue)
        fcf = float(fcf)
        shares = float(shares)
    except (TypeError, ValueError):
        return _blocked(
            quality, "missing_statements",
            "Reported revenue, free cash flow, or shares outstanding "
            "is not a number, so no DCF fair value is computed.",
        )
    if revenue <= 0 or shares <= 0:
        return _blocked(
            quality, "missing_statements",
            "Reported revenue or shares outstanding is zero or "
            "negative, so no DCF fair value is computed.",
        )
    if fcf <= 0:
        return _blocked(
            quality, "negative_fcf",
            "Reported free cash flow is zero or negative, so no DCF "
            "fair value is computed. A proxy margin is not used to "
            "replace a negative FCF.",
            reported_fcf=fcf,
        )

    price = float(price)
    market_cap = price * shares
    fcf_margin = fcf / revenue
    rev_growth_pct = statements.get("revenue_growth_pct")
    if rev_growth_pct is None and quality_verified:
        rev_growth_pct = quality.get("rev_cagr_3y_pct")
    if rev_growth_pct is None:
        rev_growth_pct = 5.0
    rev_growth = float(rev_growth_pct) / 100.0

    beta = statements.get("beta")
    debt_equity = statements.get("debt_equity") or 0
    dr = wacc_with_risk_free(beta, risk_free_rate, erp, debt_equity, sector)
    risk_free_source = (
        "live_10y_yield_supplied" if risk_free_rate is not None
        else "fallback_hardcoded_4.5pct"
    )
    wacc = {
        "wacc_pct": round(dr * 100, 1),
        "risk_free_pct": round(
            (_FALLBACK_RISK_FREE if risk_free_rate is None
             else float(risk_free_rate)) * 100, 2),
        "risk_free_source": risk_free_source,
        "erp_pct": round(
            (_FALLBACK_ERP if erp is None else float(erp)) * 100, 2),
        "beta": beta if beta is not None else 1.0,
        "beta_defaulted": beta is None,
        "sector": sector,
        "note": (
            "WACC from CAPM with sector floors, clamped to the "
            "sector floor through 15%. When risk_free_source is "
            "the fallback, the rate is hardcoded, not live."
        ),
    }

    scenarios = _scenarios(rev_growth, fcf_margin)
    try:
        from services.discovery_engine import _reverse_dcf, _run_dcf
    except Exception as exc:
        return _blocked(
            quality, "dcf_engine_unavailable",
            f"The shared DCF engine could not be loaded: {exc}.",
        )
    try:
        dcf = _run_dcf(revenue, fcf_margin, dr, scenarios, market_cap)
    except Exception as exc:
        return _blocked(
            quality, "dcf_engine_error",
            f"The shared DCF engine failed: {exc}.",
        )
    if dr <= scenarios["base"]["tg"]:
        return _blocked(
            quality, "wacc_invalid",
            "WACC is at or below terminal growth, so a Gordon "
            "terminal value cannot be computed.",
        )

    fair = {}
    upside = {}
    for name in ("bear", "base", "bull"):
        pv = dcf.get(name)
        if pv is None:
            return _blocked(
                quality, "dcf_engine_error",
                "The shared DCF engine returned no value for a scenario.",
            )
        fair[name] = round(pv / shares, 2)
        upside[name] = round((fair[name] - price) / price * 100, 1) if price else None

    try:
        reverse = _reverse_dcf(market_cap, revenue, fcf_margin, dr,
                               scenarios["base"]["tg"])
    except Exception:
        reverse = None
    try:
        sensitivity = _wacc_sensitivity(
            revenue, fcf_margin, scenarios, market_cap, shares, price)
    except Exception:
        sensitivity = []

    # Exit-multiple cross-check, base scenario only. Gordon terminal
    # value is backed out of the shared engine total, then replaced
    # by an industry EV/EBITDA terminal value. If operating margin
    # or the multiple is missing, the cross-check is unavailable,
    # never guessed.
    exit_check = None
    operating_margin = statements.get("operating_margin_pct")
    if operating_margin is None and quality_verified:
        operating_margin = quality.get("operating_margin_pct")
    ev_multiple = statements.get("ev_to_ebitda")
    if ev_multiple is None and quality_verified:
        ev_multiple = quality.get("ev_to_ebitda")
    if operating_margin is not None and ev_multiple:
        try:
            rev10 = revenue
            for _yr in range(5):
                rev10 *= (1 + scenarios["base"]["g1"])
            for _yr in range(5):
                rev10 *= (1 + scenarios["base"]["g2"])
            base = scenarios["base"]
            terminal_fcf = rev10 * base["fm"] * (1 + base["tg"])
            pv_gordon_terminal = (
                (terminal_fcf / (dr - base["tg"])) / (1 + dr) ** 10)
            pv_fcf_years = dcf["base"] - pv_gordon_terminal
            ebitda10 = rev10 * (float(operating_margin) / 100.0)
            pv_exit_terminal = (
                (ebitda10 * float(ev_multiple)) / (1 + dr) ** 10)
            exit_fair = round((pv_fcf_years + pv_exit_terminal) / shares, 2)
            disagreement = round(
                (exit_fair - fair["base"]) / fair["base"] * 100, 1
            ) if fair["base"] else None
            exit_check = {
                "method": "industry_exit_multiple_ev_ebitda",
                "multiple": float(ev_multiple),
                "fair_value": exit_fair,
                "gordon_fair_value": fair["base"],
                "disagreement_pct": disagreement,
                "wide_disagreement": bool(
                    disagreement is not None
                    and abs(disagreement) > _EXIT_DISAGREEMENT_PCT),
                "note": (
                    "Cross-check only. When wide_disagreement is true, "
                    "neither terminal method is picked as prettier. "
                    "Both fair values are shown."
                ),
            }
        except (TypeError, ValueError, ZeroDivisionError):
            exit_check = None
    if exit_check is None:
        exit_check = {
            "method": "industry_exit_multiple_ev_ebitda",
            "multiple": None,
            "fair_value": None,
            "gordon_fair_value": fair["base"],
            "disagreement_pct": None,
            "wide_disagreement": False,
            "note": (
                "Exit-multiple cross-check unavailable: operating "
                "margin or EV/EBITDA was not supplied or verified."
            ),
        }

    bear_above = fair["bear"] > price
    base_above = fair["base"] > price
    bull_above = fair["bull"] > price
    composite = quality.get("composite") if quality_verified else None
    if bear_above:
        verdict, rule, reason = (
            "strong", "margin_of_safety",
            "Even the bear case fair value is above today's price. "
            "That is a margin of safety, not a guarantee the price "
            "will rise.",
        )
    elif base_above:
        verdict, rule, reason = (
            "strong", "undervalued_central_case",
            "Base case fair value is above today's price and bear "
            "case is below, so the central case says undervalued, "
            "not bulletproof.",
        )
    elif bull_above:
        verdict, rule, reason = (
            "watch", "fairly_valued",
            "Only the bull case fair value is above today's price, "
            "so upside needs the optimistic case.",
        )
    else:
        verdict, rule, reason = (
            "weak", "overvalued",
            "All three fair values are below today's price, so it "
            "is overvalued on this DCF even if the company is strong.",
        )
    if verdict == "strong" and quality_verified and composite is not None \
            and composite < _QUALITY_STRONG_CAP:
        verdict, rule = "watch", "capped_by_quality"
        reason += (
            " Quality composite is below 50, so this is capped at "
            "WATCH rather than STRONG."
        )

    bridge_line = None
    if verdict == "strong" and base_above:
        bridge_line = "Long-term buy candidate, wait for entry"
    notes = [
        "Growth fades in the shared core from g1 in years 1 to 5 to "
        "g2 in years 6 to 10. Scenario margins drift from the "
        "reported margin: bull up to 20% higher, capped, bear 25 "
        "to 30% lower. Per-year linear fade and drift are not in "
        "that core and are not claimed here.",
        "A DCF fair value is a valuation anchor for the next 5 "
        "years of cash flows plus terminal value, not a price "
        "forecast for a date in 3 to 5 years.",
        "This lane does not change put or call gating. A strong, "
        "undervalued company can keep falling, so weekly options "
        "stay gated by timing, earnings, and SPY.",
    ]
    if exit_check.get("wide_disagreement"):
        notes.append(
            "Terminal methods disagree by more than 25%. Do not pick "
            "the higher fair value. Treat the range as uncertain."
        )

    return {
        "verdict": verdict,
        "label": verdict.upper(),
        "reason": reason,
        "reason_code": rule,
        "quality": quality,
        "dcf": {
            "fair_value": fair,
            "upside_pct": upside,
            "current_price": _money(price),
            "revenue_millions": revenue,
            "fcf_millions": fcf,
            "fcf_margin_pct": round(fcf_margin * 100, 1),
            "revenue_growth_pct": round(rev_growth * 100, 1),
            "scenarios": {
                name: {
                    "g1_pct": round(s["g1"] * 100, 1),
                    "g2_pct": round(s["g2"] * 100, 1),
                    "fcf_margin_pct": round(s["fm"] * 100, 1),
                    "terminal_growth_pct": round(s["tg"] * 100, 1),
                }
                for name, s in scenarios.items()
            },
            "reverse_dcf_implied_growth_pct": reverse,
            "exit_multiple_check": exit_check,
            "wacc_sensitivity": sensitivity,
            "method": (
                "Shared _run_dcf core, 10 years plus Gordon terminal "
                "value. Revenue and FCF are reported statement "
                "inputs, never market cap divided by P/S."
            ),
        },
        "wacc": wacc,
        "bridge_line": bridge_line,
        "bridge_entry": None,
        "notes": notes,
    }


# DCA lane, separate from timed entry and from options.
#
# DCA eligibility, stated here so it is testable and not a hidden
# threshold:
# - Quality verified, composite at least 50.0 when a composite is
#   present (the same 50 cap used for a STRONG verdict above).
#   When composite is absent but the snapshot label is
#   Compounder, that label is accepted as the quality signal.
# - Trend not broken, using the same rule as the timing verdict:
#   broken means below both averages, or below the 200-day with
#   that average falling. A broken trend gets no DCA lane.
# - Timing decision is wait, buy, or cannot_judge with known
#   trend averages. Avoid gets no DCA lane, because avoid is a
#   broken trend. A cannot_judge caused only by missing earnings
#   or market data still gets a DCA lane when trend averages are
#   known and not broken, because a long-term accumulation plan
#   does not need a timed verdict. Trend unknown still gets no
#   lane, because there is no support price to anchor to.
# - Long-term verdict: strong allows a DCA lane, valuation-backed
#   when base fair value is above price. Blocked allows a DCA
#   lane only for missing_statements, and only on a quality
#   basis, never labelled valuation-backed. Weak (overvalued on
#   a computed DCF), watch (only bull above, or capped by
#   quality), and not_verified get no DCA lane.
# - Price at a discount: price below the 50-day average, or
#   price within 3% above the 200-day average (near support).
#   Waiting for a higher trigger would mean paying more, which
#   is the point of DCA here.
#
# DCA pieces, guidance not a sized order, no share counts:
# - Piece 1, now, at the current price.
# - Piece 2, on a further dip, only if a distinct level exists:
#   the midpoint between price and the 200-day average, and
#   only when that midpoint is at least 1% below the current
#   price. NVDA on Oct 31 is the thin-range case: price $204.64,
#   200-day $204.09, midpoint $204.37, only 0.13% below price,
#   so no dip piece is forced. The plan then says so plainly
#   and has a piece now plus a piece on recovery, not a fake
#   distinct level.
# - Piece 3, on recovery to the 50-day average with confirming
#   volume, which is the timed trigger, used here as the last
#   accumulation piece, not as a timed entry price.
# - Pause rule: stop adding if the stock closes below its
#   200-day average, and reassess. Do not add into a broken
#   trend.
#
# Earnings rule, stated, not the weekly options gate reused
# silently: earnings within 5 days do NOT block a DCA lane,
# because DCA tranches span weeks, not one weekly expiry.
# Instead the lane carries an earnings note: when earnings are
# within 5 days, the first piece is the only piece before
# earnings, and later pieces come after the report. When the
# earnings date is unknown, the note says a report could move
# the price, so keep early pieces small. The reason is that a
# single report does not invalidate a long-term accumulation
# thesis, but it does argue against committing later pieces
# before it prints.
_DCA_COMPOSITE_MIN = 50.0
_DCA_NEAR_SUPPORT_PCT = 3.0
_DCA_DIP_MIN_PCT = 1.0


def _trend_broken(trend):
    if not isinstance(trend, dict):
        return True
    return bool(
        (trend.get("above_ma200") is False
         and trend.get("ma200_direction") == "falling")
        or (trend.get("above_ma50") is False
            and trend.get("above_ma200") is False)
    )


def build_dca(price, trend, longterm, stock_decision,
              earnings_days=None, earnings_known=True):
    """Build a DCA accumulation plan, or None when not eligible.

    Returns None, not a disabled plan, when any eligibility rule
    fails, so the frontend hides the lane instead of showing a
    greyed-out DCA that reads as advice. This lane never unlocks
    a weekly put or call and never changes the timing verdict.
    """
    if stock_decision not in ("wait", "buy", "cannot_judge"):
        return None
    if not isinstance(longterm, dict):
        return None
    if _trend_broken(trend):
        return None
    ma50 = trend.get("ma50")
    ma200 = trend.get("ma200")
    if ma50 is None or ma200 is None:
        return None
    try:
        price = float(price)
        ma50 = float(ma50)
        ma200 = float(ma200)
    except (TypeError, ValueError):
        return None
    quality = longterm.get("quality") or {}
    if quality.get("status") != "verified":
        return None
    composite = quality.get("composite")
    label = quality.get("label")
    if composite is not None:
        try:
            quality_ok = float(composite) >= _DCA_COMPOSITE_MIN
        except (TypeError, ValueError):
            quality_ok = False
    else:
        quality_ok = label == "Compounder"
    if not quality_ok:
        return None
    verdict = longterm.get("verdict")
    dcf = longterm.get("dcf") or {}
    fair = dcf.get("fair_value") or {}
    if verdict == "strong":
        base = fair.get("base")
        if base is None or not (base > price):
            return None
        basis = "valuation-backed"
        basis_note = (
            "Valuation-backed: base case fair value is above "
            "today's price, so the DCF supports accumulation."
        )
    elif verdict == "blocked" and longterm.get("reason_code") == "missing_statements":
        basis = "quality-based, valuation pending"
        basis_note = (
            "Quality-based, valuation pending: quality is verified "
            "and high, but no DCF fair value is computed yet, "
            "because reported revenue and free cash flow are "
            "missing. This is not valuation-backed, and it is not "
            "a weekend or market-closed issue."
        )
    else:
        return None
    discount_to_ma50 = price < ma50
    near_support = ma200 <= price <= ma200 * (1 + _DCA_NEAR_SUPPORT_PCT / 100.0)
    if not (discount_to_ma50 or near_support):
        return None
    pieces = [
        {
            "order": 1,
            "condition": "Now",
            "price": _money(price),
            "detail": "First piece now, at today's price.",
        },
    ]
    dip_note = None
    midpoint = round((price + ma200) / 2, 2)
    dip_pct = (price - midpoint) / price * 100 if price else 0
    if dip_pct >= _DCA_DIP_MIN_PCT:
        pieces.append({
            "order": 2,
            "condition": "On a further dip, still above support",
            "price": midpoint,
            "detail": (
                "Second piece only if it falls to this level, "
                "which is still above its 200-day average."
            ),
        })
    else:
        dip_note = (
            "There is no distinct lower piece above support, "
            "because the 200-day average is only "
            f"${round(price - ma200, 2)} below today's price, "
            "so the plan is a piece now and a piece on recovery, "
            "not a fake distinct level."
        )
    pieces.append({
        "order": len(pieces) + 1,
        "condition": "On recovery to the 50-day average",
        "price": _money(ma50),
        "detail": (
            "Last piece only if it recovers to its 50-day average "
            "with confirming volume. That is the timed trigger, "
            "used here as an accumulation piece, not as a timed "
            "entry price."
        ),
    })
    if earnings_known and earnings_days is not None and earnings_days <= 5:
        earnings_note = (
            f"Earnings are in {earnings_days} day(s). A report can "
            "move the price, so the first piece is the only piece "
            "before earnings, and later pieces come after the report."
        )
    elif not earnings_known:
        earnings_note = (
            "Earnings date is unknown, so a report could move the "
            "price. Keep early pieces small."
        )
    else:
        earnings_note = None
    return {
        "eligible": True,
        "label": "BEGIN DCA",
        "basis": basis,
        "basis_note": basis_note,
        "pieces": pieces,
        "dip_note": dip_note,
        "pause_rule": (
            f"Stop adding if it closes below ${round(ma200, 2)} "
            "(its 200-day average), and reassess. Do not add into "
            "a broken trend."
        ),
        "invalidation_price": _money(ma200),
        "support_price": _money(ma200),
        "trigger_price": _money(ma50),
        "discount_to_50d_pct": round((ma50 - price) / price * 100, 1) if price else None,
        "earnings_note": earnings_note,
        "note": (
            "Accumulation plan, not a timed trade setup and not a "
            "sized order. Pieces are bought in small parts, not "
            "all at once, and the pause rule above is the exit "
            "from adding."
        ),
    }
