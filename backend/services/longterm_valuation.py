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
        "composite": snapshot_entry.get("composite"),
        "label": snapshot_entry.get("label"),
        "rev_cagr_3y_pct": snapshot_entry.get("rev_cagr_3y_pct"),
        "fcf_margin_avg_3y_pct": snapshot_entry.get("fcf_margin_avg_3y_pct"),
        "roic_pct": snapshot_entry.get("roic_pct"),
        "operating_margin_pct": snapshot_entry.get("operating_margin_pct"),
        "ev_to_ebitda": snapshot_entry.get("ev_to_ebitda"),
        "fcf_yield_pct": snapshot_entry.get("fcf_yield_pct"),
        "smoothed_rule_of_40": snapshot_entry.get("smoothed_rule_of_40"),
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
        "notes": [reason],
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
                "cap divided by P/S is not used here.",
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
        upside[name] = round((fair[name] - price) / price * 100, 2) if price else None

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
                (exit_fair - fair["base"]) / fair["base"] * 100, 2
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
            "fcf_margin_pct": round(fcf_margin * 100, 2),
            "revenue_growth_pct": round(rev_growth * 100, 2),
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
