"""
On-demand ticker review, live, for any ticker the user enters.

This is an additional review, not a replacement for the snapshot
lanes in ticker_lookup. The snapshot long-term lane only trusts
the dated quality screener snapshot, so a ticker outside that
snapshot reads NOT VERIFIED and gets no DCA lane. The on-demand
review fills that gap with a dated, labelled live calculation,
shown alongside the snapshot result so the two can be compared.

Sources, reused, not a new model:
- Live quality: the same scoring as quality_screener_v2.py,
  40% smoothed Rule of 40, 30% quality, 20% consistency,
  10% valuation. The script itself is not imported, because it
  lives outside the backend package; the scoring functions here
  mirror its formulas exactly, and the weights are stated in
  every live quality payload.
- Live DCF: services.longterm_valuation.build_longterm, the
  same shared _run_dcf core, bear/base/bull, WACC, reverse DCF,
  and exit-multiple cross-check as the snapshot lane.
- Chart trend and setup: the existing timing trend data from
  ticker_lookup, price, 50-day and 200-day averages and their
  directions, RSI, volume, Quality Pullback and Volume Breakout
  conditions, SPY gate, and earnings days. No new technical
  indicator is invented here.
- AI proposals: evidence rules the user can inspect, not a
  hidden LLM verdict and not a quant decision for options.
  The app has no live LLM scoring service for this lane, so
  no LLM call is made. A proposal is a proposed score with
  evidence, source, and confidence. Until the user aligns it
  (Accept, Adjust, or Mark missing), any verdict that depends
  on it reads as AI-proposed, provisional, not final. Aligned
  scores lock with an audit trail of proposed vs aligned.
  Persistence of the alignment itself is in the frontend,
  localStorage per ticker plus date, the same pattern as the
  TwelveStep saved analyses. The backend alignment helper is
  stateless and testable: given proposals and user actions,
  it returns the aligned result.

No em dashes in this file. Put and call gating is never
changed here. Options stay gated by timing, earnings, and SPY.
"""

import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

_TV_URL = "https://scanner.tradingview.com/america/scan"
_TV_COLUMNS = [
    "name", "exchange", "market_cap_basic", "free_cash_flow_ttm",
    "total_debt", "cash_n_short_term_invest_fq",
    "free_cash_flow_margin_ttm", "operating_margin_ttm",
    "gross_margin_ttm", "return_on_invested_capital",
    "return_on_equity", "net_margin_ttm",
    "earnings_per_share_diluted_ttm", "price_earnings_ttm",
    "ebitda_ttm", "sector", "industry",
]


def _clamp(value, low, high):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(low, min(v, high))


def _pct1(value):
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _score_roic(roic):
    if roic is None:
        return None
    return _clamp(roic, 0, 30) / 30.0 * 100.0


def _score_op_margin(opm):
    if opm is None:
        return None
    return _clamp((opm - 20.0) / 30.0, 0, 1) * 100.0


def _score_gross_margin(gm):
    if gm is None:
        return None
    return _clamp((gm - 30.0) / 40.0, 0, 1) * 100.0


def _score_fcf_conversion(conv):
    if conv is None:
        return None
    return _clamp(conv, 0, 1.2) / 1.2 * 100.0


def _score_debt_ebitda(d):
    if d is None:
        return None
    if d <= 0.5:
        return 100.0
    if d <= 1.0:
        return 80.0
    if d <= 2.0:
        return 50.0
    if d <= 3.0:
        return 20.0
    return 0.0


def _score_interest_coverage(ic):
    if ic is None:
        return None
    if ic >= 10:
        return 100.0
    if ic >= 5:
        return 70.0
    if ic >= 2:
        return 30.0
    return 0.0


def _score_fcf_yield(y):
    if y is None:
        return None
    return _clamp(y, 0, 8) / 8.0 * 100.0


def _score_peg(peg):
    if peg is None:
        return 50.0
    if peg <= 0.5:
        return 90.0
    if peg <= 1.0:
        return 80.0
    if peg <= 2.0:
        return 60.0
    if peg <= 3.0:
        return 35.0
    return 10.0


def _score_ev_ebitda(ev):
    if ev is None:
        return 50.0
    if ev <= 12:
        return 100.0
    if ev <= 20:
        return 80.0
    if ev <= 30:
        return 50.0
    if ev <= 45:
        return 25.0
    return 5.0


def score_live_quality(inputs):
    """Score one ticker with the v2 weights, from supplied inputs.

    inputs is a dict with the same field names as
    quality_screener_v2.yf_check merged with a TradingView row:
    market_cap, fcf_ttm, total_debt, cash, operating_margin_ttm,
    gross_margin_ttm, roic, fcf_conversion, debt_to_ebitda,
    interest_coverage, rev_cagr_3y, fcf_margin_avg_3y,
    fcf_positive_years, rev_growth_pos_years, rev_growth_range,
    fcf_margin_range, fcf_yield, peg, ev_to_ebitda, above_200d,
    short_pct, misses.

    A missing required field is listed in missing, never scored
    as 0. Core fields are market_cap, fcf_ttm, total_debt, cash,
    and operating_margin_ttm: if any core field is missing, the
    quality status is not_verified and no composite is claimed.
    Secondary fields that are missing are averaged out, exactly
    as the v2 script averages only the available parts, and
    they are still listed in missing.
    """
    if not isinstance(inputs, dict):
        inputs = {}
    missing = []
    core = ["market_cap", "fcf_ttm", "total_debt", "cash",
            "operating_margin_ttm"]
    for field in core:
        if inputs.get(field) is None:
            missing.append(field)
    for field in ["rev_cagr_3y", "fcf_margin_avg_3y", "short_pct",
                  "misses", "roic", "gross_margin_ttm",
                  "fcf_conversion", "debt_to_ebitda",
                  "interest_coverage", "fcf_positive_years",
                  "rev_growth_pos_years", "fcf_yield", "peg",
                  "ev_to_ebitda", "above_200d"]:
        if inputs.get(field) is None:
            missing.append(field)
    short_pct = inputs.get("short_pct")
    misses = inputs.get("misses")
    kills = {
        "market_cap_at_least_1b": (
            inputs.get("market_cap") is not None
            and float(inputs["market_cap"]) >= 1_000_000_000),
        "fcf_positive": (
            inputs.get("fcf_ttm") is not None
            and float(inputs["fcf_ttm"]) > 0),
        "cash_over_debt": (
            inputs.get("cash") is not None
            and inputs.get("total_debt") is not None
            and float(inputs["cash"]) > float(inputs["total_debt"])),
        "operating_margin_at_least_20": (
            inputs.get("operating_margin_ttm") is not None
            and float(inputs["operating_margin_ttm"]) >= 20.0),
        "fewer_than_2_misses": (
            misses is not None and int(misses) < 2),
        "short_interest_nash_kill_above_10": (
            short_pct is not None and float(short_pct) > 10.0),
        "short_interest_screener_kill_above_20": (
            short_pct is not None and float(short_pct) > 20.0),
    }
    kills["nash_kills_failed"] = [
        name for name, passed in kills.items()
        if name not in ("short_interest_nash_kill_above_10",
                        "short_interest_screener_kill_above_20")
        and passed is False
    ]
    if kills["short_interest_nash_kill_above_10"]:
        kills["nash_kills_failed"].append("short_interest_above_10")
    if missing and any(f in missing for f in core):
        return {
            "status": "not_verified",
            "run_date": date.today().isoformat(),
            "source": "live_on_demand",
            "composite": None,
            "label": None,
            "rev_cagr_3y_pct": _pct1(inputs.get("rev_cagr_3y")),
            "fcf_margin_avg_3y_pct": _pct1(inputs.get("fcf_margin_avg_3y")),
            "roic_pct": _pct1(inputs.get("roic")),
            "operating_margin_pct": _pct1(inputs.get("operating_margin_ttm")),
            "ev_to_ebitda": inputs.get("ev_to_ebitda"),
            "fcf_yield_pct": _pct1(inputs.get("fcf_yield")),
            "smoothed_rule_of_40": None,
            "short_pct": short_pct,
            "misses": misses,
            "kills": kills,
            "missing": missing,
            "note": (
                "Live quality could not be verified, because a "
                "core field is missing. That field is listed, "
                "not scored as 0, and no composite is claimed."
            ),
        }
    cagr = inputs.get("rev_cagr_3y")
    margin_avg = inputs.get("fcf_margin_avg_3y")
    cagr_capped = _clamp(cagr, -20, 50) if cagr is not None else 0.0
    margin_capped = _clamp(margin_avg, 0, 50) if margin_avg is not None else 0.0
    smoothed = round(cagr_capped + margin_capped, 1)
    ro40_score = round(_clamp(cagr_capped + margin_capped, 0, 100), 1)
    quality_parts = [
        _score_roic(inputs.get("roic")),
        _score_op_margin(inputs.get("operating_margin_ttm")),
        _score_gross_margin(inputs.get("gross_margin_ttm")),
        _score_fcf_conversion(inputs.get("fcf_conversion")),
        _score_debt_ebitda(inputs.get("debt_to_ebitda")),
        _score_interest_coverage(inputs.get("interest_coverage")),
    ]
    quality_avail = [s for s in quality_parts if s is not None]
    quality_score = round(sum(quality_avail) / len(quality_avail), 1) if quality_avail else 50.0
    cons_parts = []
    if inputs.get("fcf_positive_years") is not None:
        cons_parts.append(float(inputs["fcf_positive_years"]) / 4.0 * 100.0)
    if inputs.get("rev_growth_pos_years") is not None:
        cons_parts.append(float(inputs["rev_growth_pos_years"]) / 3.0 * 100.0)
    if misses is not None:
        cons_parts.append(100.0 if int(misses) == 0 else 70.0)
    consistency_score = round(sum(cons_parts) / len(cons_parts), 1) if cons_parts else 50.0
    val_parts = [
        _score_fcf_yield(inputs.get("fcf_yield")),
        _score_peg(inputs.get("peg")),
        _score_ev_ebitda(inputs.get("ev_to_ebitda")),
        100.0 if inputs.get("above_200d") is True else (
            30.0 if inputs.get("above_200d") is False else 50.0),
    ]
    val_avail = [s for s in val_parts if s is not None]
    valuation_score = round(sum(val_avail) / len(val_avail), 1) if val_avail else 50.0
    composite = round(
        0.40 * ro40_score + 0.30 * quality_score
        + 0.20 * consistency_score + 0.10 * valuation_score, 1)
    growth_range = inputs.get("rev_growth_range")
    margin_range = inputs.get("fcf_margin_range")
    basis = []
    if growth_range is not None and growth_range > 100:
        basis.append(f"revenue growth range {growth_range:.0f}pts")
    if margin_range is not None and margin_range > 40:
        basis.append(f"FCF margin range {margin_range:.0f}pts")
    if basis:
        label, label_basis = "Cyclical", ", ".join(basis)
    elif consistency_score >= 70 and quality_score >= 60:
        label = "Compounder"
        label_basis = f"consistency {consistency_score:.0f}, quality {quality_score:.0f}"
    else:
        label = "Steady"
        label_basis = f"consistency {consistency_score:.0f}, quality {quality_score:.0f}"
    return {
        "status": "verified",
        "run_date": date.today().isoformat(),
        "source": "live_on_demand",
        "composite": composite,
        "label": label,
        "label_basis": label_basis,
        "rev_cagr_3y_pct": _pct1(cagr),
        "fcf_margin_avg_3y_pct": _pct1(margin_avg),
        "roic_pct": _pct1(inputs.get("roic")),
        "operating_margin_pct": _pct1(inputs.get("operating_margin_ttm")),
        "ev_to_ebitda": inputs.get("ev_to_ebitda"),
        "fcf_yield_pct": _pct1(inputs.get("fcf_yield")),
        "smoothed_rule_of_40": smoothed,
        "quality_score": quality_score,
        "consistency_score": consistency_score,
        "valuation_score": valuation_score,
        "short_pct": short_pct,
        "misses": misses,
        "kills": kills,
        "missing": missing,
        "note": (
            "Live quality, computed today with the v2 weights "
            "(40% smoothed Rule of 40, 30% quality, 20% "
            "consistency, 10% valuation). It is not the "
            "2026-10-26 snapshot, and it will move as data move."
        ),
    }


def fetch_live_quality_inputs(ticker):
    """Fetch TradingView single-ticker row plus yfinance history.

    Best effort, never raising: any failed source leaves its
    fields as None, so score_live_quality can mark them missing.
    TradingView is queried by ticker symbol for NASDAQ and NYSE
    in turn. yfinance history follows the same series logic as
    quality_screener_v2.yf_check.
    """
    ticker = (ticker or "").upper().strip()
    tv_row = {}
    try:
        import urllib.request

        for exchange in ("NASDAQ", "NYSE"):
            body = json.dumps({
                "symbols": {"query": {"types": ["stock"]},
                            "tickers": [f"{exchange}:{ticker}"]},
                "columns": _TV_COLUMNS,
                "options": {"lang": "en"},
                "range": [0, 1],
            }).encode()
            req = urllib.request.Request(
                _TV_URL, data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            rows = data.get("data") or []
            if rows:
                tv_row = dict(zip(_TV_COLUMNS, rows[0].get("d") or []))
                break
    except Exception as exc:
        logger.warning("on-demand TradingView fetch failed for %s: %s", ticker, exc)
    inputs = {
        "market_cap": tv_row.get("market_cap_basic"),
        "fcf_ttm": tv_row.get("free_cash_flow_ttm"),
        "total_debt": tv_row.get("total_debt"),
        "cash": tv_row.get("cash_n_short_term_invest_fq"),
        "operating_margin_ttm": tv_row.get("operating_margin_ttm"),
        "gross_margin_ttm": tv_row.get("gross_margin_ttm"),
        "roic": tv_row.get("return_on_invested_capital"),
        "ebitda": tv_row.get("ebitda_ttm"),
        "short_pct": None, "misses": None,
        "rev_cagr_3y": None, "fcf_margin_avg_3y": None,
        "fcf_positive_years": None, "rev_growth_pos_years": None,
        "rev_growth_range": None, "fcf_margin_range": None,
        "fcf_conversion": None, "debt_to_ebitda": None,
        "interest_coverage": None, "fcf_yield": None,
        "peg": None, "ev_to_ebitda": None, "above_200d": None,
    }
    try:
        import yfinance as yf

        t = yf.Ticker(ticker.replace(".", "-"))
        info = t.info or {}
        sp = info.get("shortPercentOfFloat")
        if sp is not None:
            inputs["short_pct"] = round(float(sp) * 100.0, 2)
        inputs["peg"] = info.get("pegRatio")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        ma200 = info.get("twoHundredDayAverage")
        if price is not None and ma200:
            inputs["above_200d"] = bool(float(price) > float(ma200))
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty and "Surprise(%)" in ed.columns:
                reported = ed.dropna(subset=["Reported EPS", "EPS Estimate"])
                last4 = reported.tail(4)
                if len(last4) >= 4:
                    inputs["misses"] = int((last4["Surprise(%)"] < 0).sum())
        except Exception as exc:
            logger.warning("on-demand earnings fetch failed for %s: %s", ticker, exc)
        try:
            fin = t.financials
            cf = t.cashflow

            def series(df, name):
                out = []
                if df is None or name not in getattr(df, "index", []):
                    return out
                for ts, val in df.loc[name].dropna().items():
                    year = int(getattr(ts, "year", 0))
                    if year and val == val:
                        out.append((year, float(val)))
                return sorted(out)

            rev_hist = series(fin, "Total Revenue")
            net_hist = series(fin, "Net Income")
            ocf = dict(series(cf, "Operating Cash Flow"))
            capex = dict(series(cf, "Capital Expenditure"))
            fcf_hist = sorted(
                (y, ocf[y] + capex[y])
                for y in sorted(set(ocf) & set(capex)))
            if len(rev_hist) >= 4 and rev_hist[0][1] > 0:
                rev_sorted = rev_hist[-4:]
                cagr = (rev_sorted[-1][1] / rev_sorted[0][1]) ** (1.0 / 3.0) - 1.0
                inputs["rev_cagr_3y"] = round(cagr * 100.0, 1)
                growths = []
                for i in range(1, len(rev_sorted)):
                    if rev_sorted[i - 1][1] > 0:
                        growths.append(
                            (rev_sorted[i][1] / rev_sorted[i - 1][1] - 1.0) * 100.0)
                inputs["rev_growth_pos_years"] = int(sum(1 for g in growths if g > 0))
                if growths:
                    inputs["rev_growth_range"] = round(max(growths) - min(growths), 1)
            rev_d = dict(rev_hist)
            fcf_d = dict(fcf_hist)
            years = sorted(set(rev_d) & set(fcf_d))
            margins = []
            for y in years[-3:]:
                if rev_d.get(y):
                    margins.append(fcf_d[y] / rev_d[y] * 100.0)
            if margins:
                inputs["fcf_margin_avg_3y"] = round(sum(margins) / len(margins), 1)
            margins4 = []
            for y in years[-4:]:
                if rev_d.get(y):
                    margins4.append(fcf_d[y] / rev_d[y] * 100.0)
            if margins4:
                inputs["fcf_margin_range"] = round(max(margins4) - min(margins4), 1)
            fcf_years = fcf_hist[-4:]
            if fcf_years:
                inputs["fcf_positive_years"] = int(sum(1 for _, v in fcf_years if v > 0))
            if inputs["fcf_ttm"] is not None and net_hist:
                net_ttm = net_hist[-1][1]
                if net_ttm:
                    inputs["fcf_conversion"] = round(float(inputs["fcf_ttm"]) / float(net_ttm), 2)
            if inputs["total_debt"] is not None and inputs["ebitda"]:
                inputs["debt_to_ebitda"] = round(float(inputs["total_debt"]) / float(inputs["ebitda"]), 2)
            if inputs["market_cap"] and inputs["fcf_ttm"]:
                inputs["fcf_yield"] = round(float(inputs["fcf_ttm"]) / float(inputs["market_cap"]) * 100.0, 2)
            ev = None
            if inputs["ebitda"] and inputs["market_cap"] is not None and inputs["total_debt"] is not None:
                cash = inputs["cash"] or 0
                if float(inputs["ebitda"]) > 0:
                    ev = (float(inputs["market_cap"]) + float(inputs["total_debt"]) - float(cash)) / float(inputs["ebitda"])
            inputs["ev_to_ebitda"] = round(ev, 1) if ev is not None else info.get("enterpriseToEbitda")
        except Exception as exc:
            logger.warning("on-demand yfinance history failed for %s: %s", ticker, exc)
    except Exception as exc:
        logger.warning("on-demand yfinance fetch failed for %s: %s", ticker, exc)
    return inputs


def fetch_statements(ticker, price):
    """Polygon SEC latest annual plus Finnhub shares, in millions.

    Returns (statements_dict_or_None, note). Statements are
    revenue_millions, fcf_millions, shares_outstanding_millions,
    beta, sector, plus the cross-check fields. If Polygon
    returns no revenue or FCF, or shares are missing, statements
    are None and the DCF stays BLOCKED. If price times shares
    differs from the Finnhub market cap by more than 25%,
    statements are also None, because the share count does not
    reconcile, and the note says so plainly.
    """
    ticker = (ticker or "").upper().strip()
    try:
        from services.polygon_client import get_financials
        from services.finnhub_client import get_basic_financials, get_company_profile
    except Exception as exc:
        return None, f"Statements sources could not be loaded: {exc}."
    try:
        fin = get_financials(ticker) or {}
    except Exception as exc:
        logger.warning("on-demand Polygon financials failed for %s: %s", ticker, exc)
        fin = {}
    revenue = fin.get("revenue")
    fcf = fin.get("free_cash_flow")
    if revenue is None or fcf is None:
        return None, "Polygon SEC financials returned no revenue or free cash flow, so no DCF is computed."
    try:
        profile = get_company_profile(ticker) or {}
        basics = get_basic_financials(ticker) or {}
    except Exception:
        profile, basics = {}, {}
    shares = profile.get("shareOutstanding") or basics.get("sharesOutstanding")
    if shares is None:
        return None, "Shares outstanding are missing, so no DCF is computed."
    try:
        shares = float(shares)
        revenue_m = float(revenue) / 1_000_000.0
        fcf_m = float(fcf) / 1_000_000.0
    except (TypeError, ValueError):
        return None, "Statement values are not numbers, so no DCF is computed."
    market_cap_profile = profile.get("marketCapitalization")
    if market_cap_profile is not None and price:
        try:
            implied = float(price) * shares
            base = float(market_cap_profile)
            if base > 0 and abs(implied - base) / base > 0.25:
                return None, (
                    "Share count does not reconcile: price times "
                    "shares differs from the profile market cap by "
                    "more than 25%, so no DCF is computed on it."
                )
        except (TypeError, ValueError):
            pass
    statements = {
        "revenue": revenue_m,
        "fcf": fcf_m,
        "shares_outstanding": shares,
        "beta": basics.get("beta"),
        "sector": profile.get("finnhubIndustry") or profile.get("gics_sector"),
        "debt_equity": None,
    }
    debt = fin.get("total_debt")
    equity = fin.get("equity")
    if debt is not None and equity:
        try:
            statements["debt_equity"] = float(debt) / float(equity)
        except (TypeError, ValueError, ZeroDivisionError):
            statements["debt_equity"] = None
    return statements, "Polygon SEC latest annual, converted to millions, shares from Finnhub profile."


def build_short_term(price, trend, stock, setups, spy_gate, earnings):
    """Short-term trend and setup, from existing timing data only."""
    if not isinstance(trend, dict):
        trend = {}
    ma50 = trend.get("ma50")
    ma200 = trend.get("ma200")
    above50 = trend.get("above_ma50")
    above200 = trend.get("above_ma200")
    if ma50 is None or ma200 is None:
        trend_label = "unknown"
        trend_note = "Trend averages are not available, so no short-term trend is claimed."
    elif above50 is False and above200 is False:
        trend_label = "broken"
        trend_note = "Short-term trend is broken: price is below both its 50-day and 200-day averages."
    elif above200 is False and trend.get("ma200_direction") == "falling":
        trend_label = "broken"
        trend_note = "Short-term trend is broken: price is below a falling 200-day average."
    elif above50 and above200:
        trend_label = "up"
        trend_note = "Short-term trend is up: price is above its 50-day and 200-day averages."
    elif above50 is False:
        trend_label = "weak"
        trend_note = "Short-term trend is weak: price is below its 50-day average."
    else:
        trend_label = "weak"
        trend_note = "Short-term trend is weak: price is below one of its averages."
    passing = []
    for setup in setups or []:
        if setup.get("rule_result") == "pass" and setup.get("status") == "LIVE":
            passing.append(setup.get("setup_name") or setup.get("setup_key"))
    entry_plan = (stock or {}).get("entry_plan") or {}
    return {
        "trend": trend_label,
        "trend_note": trend_note,
        "price": price,
        "ma50": ma50,
        "ma200": ma200,
        "ma50_direction": trend.get("ma50_direction"),
        "ma200_direction": trend.get("ma200_direction"),
        "setup_present": bool(passing),
        "setup_names": passing,
        "timing_decision": (stock or {}).get("decision"),
        "timing_label": (stock or {}).get("label"),
        "pullback_price": entry_plan.get("pullback_price"),
        "breakout_price": entry_plan.get("breakout_price"),
        "buy_zone": entry_plan.get("buy_zone"),
        "invalidation_price": entry_plan.get("invalidation_price"),
        "what_flips_to_buy": entry_plan.get("what_flips_to_buy"),
        "spy_above_200": (spy_gate or {}).get("spy_above_200"),
        "earnings_days": (earnings or {}).get("days_away"),
        "earnings_status": (earnings or {}).get("status"),
        "note": (
            "Chart setup only. A setup present does not make a "
            "weak company a long-term buy, and a strong company "
            "with no setup is not a timed buy today."
        ),
    }


def build_dca_decision(price, trend, longterm, stock_decision,
                       earnings_days=None, earnings_known=True):
    """Explicit DCA decision: now, later, avoid, or cannot_judge.

    build_dca from longterm_valuation is reused for the Now
    plan. Every other outcome names its reason, so Later is
    never a silent fallback for Avoid, and Cannot judge is
    never presented as an avoid.
    """
    from services.longterm_valuation import build_dca, _trend_broken

    if not isinstance(longterm, dict):
        longterm = {}
    if not isinstance(trend, dict):
        trend = {}
    quality = longterm.get("quality") or {}
    verdict = longterm.get("verdict")
    kills = quality.get("kills") or {}
    kill_reasons = []
    if kills.get("fcf_positive") is False:
        kill_reasons.append("free cash flow is not positive")
    if kills.get("cash_over_debt") is False:
        kill_reasons.append("cash is not greater than debt")
    if kills.get("operating_margin_at_least_20") is False:
        kill_reasons.append("operating margin is below 20%")
    if kills.get("fewer_than_2_misses") is False:
        kill_reasons.append("2 or more earnings misses in the last 4 quarters")
    if kills.get("short_interest_nash_kill_above_10"):
        kill_reasons.append("short interest is above 10% (Nash Step 3 kill)")
    if _trend_broken(trend) or stock_decision == "avoid":
        return {
            "decision": "avoid", "label": "AVOID COMPLETELY",
            "reason": "Trend is broken (timing AVOID), so no accumulation is offered, even if the company is strong.",
            "killing_parameters": ["trend broken"],
            "plan": None, "trigger": None, "trigger_price": None,
        }
    # Missing checks come before kill reasons: a kill derived
    # from missing data is not a verified kill. Cannot judge is
    # not an avoid, and it is not a buy.
    if quality.get("status") != "verified" or verdict in ("not_verified", None):
        missing = quality.get("missing") or ["quality not verified"]
        return {
            "decision": "cannot_judge", "label": "CANNOT JUDGE",
            "reason": "A required check is missing, so no DCA decision is claimed. Missing: " + ", ".join(str(m) for m in missing) + ".",
            "killing_parameters": [],
            "missing": missing,
            "plan": None, "trigger": None, "trigger_price": None,
        }
    if verdict == "weak":
        return {
            "decision": "avoid", "label": "AVOID COMPLETELY",
            "reason": "The DCF says it is overvalued: all fair values are below today's price.",
            "killing_parameters": ["DCF overvalued"],
            "plan": None, "trigger": None, "trigger_price": None,
        }
    if kill_reasons:
        return {
            "decision": "avoid", "label": "AVOID COMPLETELY",
            "reason": "A core Nash kill fails: " + "; ".join(kill_reasons) + ".",
            "killing_parameters": kill_reasons,
            "plan": None, "trigger": None, "trigger_price": None,
        }
    if trend.get("ma50") is None or trend.get("ma200") is None:
        return {
            "decision": "cannot_judge", "label": "CANNOT JUDGE",
            "reason": "Trend averages are missing, so there is no support price to anchor a DCA plan to.",
            "killing_parameters": [], "missing": ["ma50", "ma200"],
            "plan": None, "trigger": None, "trigger_price": None,
        }
    plan = build_dca(price, trend, longterm, stock_decision,
                     earnings_days=earnings_days, earnings_known=earnings_known)
    if plan is not None:
        return {
            "decision": "now", "label": "BEGIN DCA NOW",
            "reason": "Quality is verified, trend is not broken, price is near support, and " + plan.get("basis", "") + ".",
            "killing_parameters": [], "plan": plan,
            "trigger": "now", "trigger_price": price,
        }
    ma50 = trend.get("ma50")
    ma200 = trend.get("ma200")
    try:
        price_f = float(price)
        ma50_f = float(ma50)
        ma200_f = float(ma200)
    except (TypeError, ValueError):
        return {
            "decision": "cannot_judge", "label": "CANNOT JUDGE",
            "reason": "Price or trend averages are not numbers, so no DCA decision is claimed.",
            "killing_parameters": [], "missing": ["price_or_trend"],
            "plan": None, "trigger": None, "trigger_price": None,
        }
    if verdict == "watch":
        fair = (longterm.get("dcf") or {}).get("fair_value") or {}
        base = fair.get("base")
        return {
            "decision": "later", "label": "DCA LATER",
            "reason": "Quality is verified and trend is not broken, but the DCF only supports the bull case, so wait for a better valuation.",
            "killing_parameters": [], "plan": None,
            "trigger": "price at or below base fair value, or a fundamentals update that lifts base fair value above price",
            "trigger_price": base,
        }
    if not (price_f < ma50_f or ma200_f <= price_f <= ma200_f * 1.03):
        return {
            "decision": "later", "label": "DCA LATER",
            "reason": "Quality is verified and trend is not broken, but price is not near support, so wait for a pullback instead of chasing it.",
            "killing_parameters": [], "plan": None,
            "trigger": "pullback to the 50-day average",
            "trigger_price": ma50_f,
        }
    return {
        "decision": "cannot_judge", "label": "CANNOT JUDGE",
        "reason": "DCA eligibility could not be confirmed from the supplied long-term and trend data, so no decision is claimed.",
        "killing_parameters": [], "missing": ["dca_eligibility"],
        "plan": None, "trigger": None, "trigger_price": None,
    }


def _confidence_for(evidence_count, missing_count):
    if missing_count:
        return "low"
    if evidence_count >= 3:
        return "high"
    if evidence_count >= 2:
        return "medium"
    return "low"


def propose_moat(quality, profile):
    """Evidence-based moat proposal, 0/5/10, Nash scorecard category 8."""
    if not isinstance(quality, dict):
        quality = {}
    if not isinstance(profile, dict):
        profile = {}
    description = (profile.get("description") or profile.get("business") or "").lower()
    industry = (profile.get("industry") or profile.get("finnhubIndustry") or "").lower()
    text = description + " " + industry
    types = []
    if any(k in text for k in ("network", "platform", "marketplace", "social")):
        types.append("network effects")
    if any(k in text for k in ("patent", "semiconductor", "chip", "proprietary", "software")):
        types.append("technology and patents")
    if any(k in text for k in ("subscription", "enterprise", "saas", "contract")):
        types.append("switching costs")
    if any(k in text for k in ("retail", "logistics", "manufacturing", "scale")):
        types.append("scale")
    if any(k in text for k in ("defense", "healthcare", "license", "regulated", "approval")):
        types.append("regulation")
    if any(k in text for k in ("brand", "consumer", "beverage", "luxury")):
        types.append("brand")
    proxies = []
    if quality.get("roic_pct") is not None and float(quality["roic_pct"]) >= 20:
        proxies.append(f"ROIC {quality['roic_pct']}% at or above 20%")
    if quality.get("operating_margin_pct") is not None and float(quality["operating_margin_pct"]) >= 25:
        proxies.append(f"operating margin {quality['operating_margin_pct']}% at or above 25%")
    fcf_margin = quality.get("fcf_margin_avg_3y_pct")
    if fcf_margin is not None and float(fcf_margin) >= 20:
        proxies.append(f"FCF margin avg 3y {fcf_margin}% at or above 20%")
    gross = None
    if isinstance(profile, dict):
        gross = profile.get("gross_margin_pct")
    if gross is not None and float(gross) >= 50:
        proxies.append(f"gross margin {gross}% at or above 50%")
    evidence = []
    if types:
        evidence.append("Moat types suggested by business description or industry: " + ", ".join(types) + ".")
    if proxies:
        evidence.append("Quant proxies: " + "; ".join(proxies) + ".")
    if not types and not proxies:
        evidence.append("No moat type and no quant proxy was found in the supplied data, so no moat is proposed.")
    if types and len(proxies) >= 2:
        score, label = 10, "Strong"
    elif types or len(proxies) >= 1:
        score, label = 5, "Weak"
    else:
        score, label = 0, "None"
    return {
        "key": "moat", "name": "Moat strength",
        "proposed_score": score, "proposed_label": label,
        "moat_types": types,
        "evidence": evidence,
        "source": "business description and industry, plus ROIC, operating margin, and FCF margin proxies",
        "confidence": _confidence_for(len(types) + len(proxies), 0 if (types or proxies) else 1),
        "missing": [] if (types or proxies) else ["moat_evidence"],
    }


def propose_ceo(tenure):
    """Evidence-based CEO proposal, 0/5/10, Nash scorecard category 9.

    tenure is a dict: founder (bool), years_in_role, revenue_cagr_tenure_pct,
    margin_change_pp, return_vs_sp500_pp, insider_net_shares,
    insider_buyers, insider_sellers, dilution_note. Any field may be
    None, and a missing field is listed, never guessed. Founder
    status is a plus, not an automatic top score: a founder with
    flat margins and heavy dilution must not propose Superstar.
    """
    if not isinstance(tenure, dict):
        tenure = {}
    evidence = []
    missing = []
    founder = tenure.get("founder")
    years = tenure.get("years_in_role")
    if founder is True:
        evidence.append("Founder CEO, a Nash plus.")
    elif founder is False:
        evidence.append("Non-founder CEO.")
    else:
        missing.append("founder_status")
    if years is not None:
        evidence.append(f"{years} years in role.")
        if years >= 10:
            evidence.append("10 or more years in role, a Nash plus.")
    else:
        missing.append("years_in_role")
    rev_cagr = tenure.get("revenue_cagr_tenure_pct")
    if rev_cagr is not None:
        evidence.append(f"Revenue CAGR during tenure: {rev_cagr}%.")
    else:
        missing.append("revenue_cagr_tenure")
    margin_change = tenure.get("margin_change_pp")
    if margin_change is not None:
        evidence.append(f"Operating margin change during tenure: {margin_change} points.")
    else:
        missing.append("margin_change_tenure")
    ret_vs = tenure.get("return_vs_sp500_pp")
    if ret_vs is not None:
        evidence.append(f"Shareholder return vs S&P 500 during tenure: {ret_vs} points.")
    else:
        missing.append("return_vs_sp500_tenure")
    insider_net = tenure.get("insider_net_shares")
    if insider_net is not None:
        if insider_net > 0:
            evidence.append(f"Open-market insider net buying: {insider_net} shares.")
        elif insider_net < 0:
            evidence.append(f"Open-market insider net selling: {abs(insider_net)} shares.")
        else:
            evidence.append("Open-market insider net flow is flat.")
    else:
        missing.append("insider_net_shares")
    if tenure.get("dilution_note"):
        evidence.append(str(tenure["dilution_note"]))
    strong = (
        founder is True and years is not None and years >= 10
        and rev_cagr is not None and rev_cagr >= 10
        and margin_change is not None and margin_change >= 2
        and ret_vs is not None and ret_vs >= 0
    )
    if tenure.get("dilution_note") and "dilut" in str(tenure["dilution_note"]).lower():
        # Founder status plus heavy dilution is never Superstar,
        # even if revenue grew. Flat margins already fail the
        # margin expansion check above, so this is a second guard.
        strong = False
    weak_negative = (
        (rev_cagr is not None and rev_cagr < 0)
        or (margin_change is not None and margin_change < -10)
        or (insider_net is not None and insider_net < 0
            and tenure.get("insider_sellers", 0) >= 2)
    )
    if strong:
        score, label = 10, "Superstar"
    elif weak_negative and not (founder is True and years is not None and years >= 10 and rev_cagr is not None and rev_cagr >= 5):
        score, label = 0, "Clown"
    elif years is not None and years >= 10 and rev_cagr is not None and rev_cagr >= 5:
        score, label = 5, "Decent"
    elif rev_cagr is not None and rev_cagr >= 5 and margin_change is not None and margin_change >= -5:
        score, label = 5, "Decent"
    else:
        score, label = 5, "Decent"
    if not evidence:
        score, label = 5, "Decent"
    return {
        "key": "ceo", "name": "CEO quality",
        "proposed_score": score, "proposed_label": label,
        "evidence": evidence if evidence else ["No CEO tenure or execution evidence was supplied, so the proposal is low confidence."],
        "source": "CEO tenure, founder status, tenure revenue and margin change, return vs S&P 500, and open-market insider flow",
        "confidence": _confidence_for(len(evidence), len(missing)),
        "missing": missing,
    }


def propose_market_size(market):
    """Evidence-based market size proposal, Nash Step 5, not a score.

    market is a dict: tam_millions, tam_low_millions,
    tam_high_millions, source, source_date, source_type
    (filing, independent, analyst), growth_pct. If no TAM is
    supplied, the proposal is missing, never guessed.
    """
    if not isinstance(market, dict):
        market = {}
    tam = market.get("tam_millions") or market.get("tam_high_millions")
    if tam is None:
        return {
            "key": "market_size", "name": "Market size",
            "proposed_score": None, "proposed_label": "Missing",
            "evidence": ["No total market size source was supplied, so no market size is proposed. Supply a filing or industry source in the Nash wizard Step 5."],
            "source": "none supplied",
            "confidence": "low",
            "missing": ["tam"],
            "tam_millions": None, "tam_low_millions": None,
            "tam_high_millions": None, "source_type": None,
            "source_date": None, "broad": None,
            "supports_growth_bet": None,
        }
    revenue_m = market.get("revenue_millions")
    broad = None
    supports = None
    try:
        if float(tam) >= 50_000:
            broad = True
        elif float(tam) < 10_000:
            broad = False
        if revenue_m:
            supports = float(tam) / float(revenue_m) >= 10
    except (TypeError, ValueError):
        broad, supports = None, None
    evidence = [f"Total market: ${tam} million, source: {market.get('source') or 'not named'}, type: {market.get('source_type') or 'not named'}, date: {market.get('source_date') or 'not named'}."]
    if market.get("growth_pct") is not None:
        evidence.append(f"Market growth: {market['growth_pct']}%.")
    return {
        "key": "market_size", "name": "Market size",
        "proposed_score": None,
        "proposed_label": "Broad" if broad else ("Niche" if broad is False else "Unknown"),
        "evidence": evidence,
        "source": market.get("source") or "not named",
        "confidence": "high" if market.get("source_type") in ("filing", "independent") else "medium",
        "missing": [],
        "tam_millions": tam,
        "tam_low_millions": market.get("tam_low_millions"),
        "tam_high_millions": market.get("tam_high_millions"),
        "source_type": market.get("source_type"),
        "source_date": market.get("source_date"),
        "broad": broad,
        "supports_growth_bet": supports,
    }


def build_proposals(quality, profile, tenure=None, market=None):
    """All three AI proposals, evidence rules only, no LLM call."""
    return {
        "moat": propose_moat(quality, profile),
        "ceo": propose_ceo(tenure or {}),
        "market_size": propose_market_size(market or {}),
    }


def apply_alignment(proposals, actions):
    """Apply user alignment to proposals, stateless and testable.

    actions: {key: {"action": "accept"|"adjust"|"missing", "score": int|None}}
    Returns aligned proposals, an audit trail, and a status:
    locked when every proposal has an action, provisional when
    any proposal is still unaligned. A marked-missing proposal
    is resolved, not unaligned, and its aligned score is None.
    An adjusted score must be 0, 5, or 10, otherwise the action
    is ignored and the proposal stays unaligned.
    """
    if not isinstance(proposals, dict):
        proposals = {}
    if not isinstance(actions, dict):
        actions = {}
    aligned = {}
    audit = []
    all_resolved = True
    for key, proposal in proposals.items():
        act = actions.get(key) or {}
        action = act.get("action")
        if action == "accept":
            aligned_score = proposal.get("proposed_score")
            status = "accepted"
        elif action == "adjust":
            score = act.get("score")
            if score in (0, 5, 10):
                aligned_score = score
                status = "adjusted"
            else:
                aligned_score = None
                status = "unaligned"
                all_resolved = False
        elif action == "missing":
            aligned_score = None
            status = "missing"
        else:
            aligned_score = None
            status = "unaligned"
            all_resolved = False
        aligned[key] = {
            **proposal,
            "aligned_score": aligned_score,
            "alignment_status": status,
        }
        audit.append({
            "key": key,
            "proposed_score": proposal.get("proposed_score"),
            "aligned_score": aligned_score,
            "alignment_status": status,
        })
    return {
        "proposals": aligned,
        "audit_trail": audit,
        "status": "locked" if all_resolved and aligned else "provisional",
        "provisional": not (all_resolved and aligned),
    }


def build_ondemand_summary(ticker, short_term, longterm, dca_decision,
                           alignment_status):
    """Plain-language summary for the on-demand review, in order."""
    parts = []
    parts.append(f"On-demand review for {ticker}, live, not the 2026-10-26 snapshot.")
    if short_term:
        parts.append(short_term.get("trend_note") or "")
        if short_term.get("setup_present"):
            parts.append("A short-term setup is present: " + ", ".join(short_term.get("setup_names") or []) + ".")
        else:
            parts.append("No short-term setup is present today.")
    if longterm:
        parts.append(f"Long-term: {longterm.get('label')}. {longterm.get('reason') or ''}")
    if dca_decision:
        parts.append(f"DCA decision: {dca_decision.get('label')}. {dca_decision.get('reason') or ''}")
        if dca_decision.get("trigger"):
            parts.append(f"Trigger: {dca_decision['trigger']}.")
    if alignment_status == "provisional":
        parts.append("AI proposals are provisional until you align them. They do not yet count as final scores.")
    return " ".join(p for p in parts if p)


def build_ondemand_review(ticker, price, trend, stock, setups, spy_gate,
                          earnings, quality_live, longterm_live,
                          proposals, alignment=None):
    """Assemble the on-demand review from already-computed parts."""
    short_term = build_short_term(price, trend, stock, setups, spy_gate, earnings)
    stock_decision = (stock or {}).get("decision")
    earnings_days = (earnings or {}).get("days_away")
    earnings_known = (earnings or {}).get("status") == "known"
    dca_decision = build_dca_decision(
        price, trend, longterm_live, stock_decision,
        earnings_days=earnings_days, earnings_known=earnings_known)
    alignment_result = apply_alignment(proposals or {}, alignment or {})
    summary = build_ondemand_summary(
        ticker, short_term, longterm_live, dca_decision,
        alignment_result["status"])
    return {
        "ticker": ticker,
        "run_date": date.today().isoformat(),
        "source": "live_on_demand",
        "summary": summary,
        "short_term": short_term,
        "longterm": longterm_live,
        "dca_decision": dca_decision,
        "proposals": alignment_result["proposals"],
        "alignment": {
            "status": alignment_result["status"],
            "provisional": alignment_result["provisional"],
            "audit_trail": alignment_result["audit_trail"],
        },
        "note": (
            "Additional review only. It does not replace the "
            "snapshot long-term lane, and it does not change "
            "put or call gating, which stays gated by timing, "
            "earnings, and SPY."
        ),
    }
