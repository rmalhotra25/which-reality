"""
Standalone DCF analysis service.

For a given ticker:
  1. Fetches fundamentals + beta from Finnhub
  2. Derives CAPM-based WACC from beta
  3. Computes reverse DCF (implied growth rate priced in at current market cap)
  4. Asks Claude for commentary only (reasoning and confidence),
     never for scenario parameters. A commentary failure changes
     nothing: the mechanical scenarios still run.
  5. Runs forward 10-year FCF DCF and returns per-share price targets

This is the same model used in the discovery picks but with a dedicated
Claude call focused entirely on scenario-setting for one company.
"""
import logging

from services.finnhub_client import get_basic_financials, get_company_profile
from services.discovery_engine import _wacc_from_beta, _reverse_dcf, _run_dcf

logger = logging.getLogger(__name__)

# Risk-free rate and equity risk premium for CAPM
_RF = 0.045
_ERP = 0.055


def _build_fundamentals(ticker: str) -> dict | None:
    """Fetch and normalise all inputs needed for the DCF."""
    metrics = get_basic_financials(ticker)
    if not metrics:
        return None
    mc = metrics.get("marketCapitalization")
    if not mc or mc <= 0:
        return None

    profile = get_company_profile(ticker) or {}

    fcf_margin = (
        metrics.get("fcfMarginTTM") or
        metrics.get("freeCashFlowMarginTTM") or
        metrics.get("fcfMargin5Y") or 0
    )
    roic = (
        metrics.get("roicTTM") or
        metrics.get("returnOnInvestedCapitalTTM") or
        metrics.get("roiTTM")
    )
    rev_growth_q = (
        metrics.get("revenueGrowth3M") or
        metrics.get("revenueGrowthQuarterlyYoy") or
        metrics.get("revenueGrowth1Q")
    )

    gross_margin_raw = metrics.get("grossMarginTTM")
    gross_margin_reliable = (
        gross_margin_raw is not None and
        gross_margin_raw > 0 and
        gross_margin_raw < 95
    )
    gross_margin_note = (
        "reported" if gross_margin_reliable else
        "unreliable — Finnhub returned null or zero. "
        "Derive FCF margin from operating_margin, "
        "net_margin, and sector benchmarks instead."
    )

    sector = profile.get("finnhubIndustry", "Unknown")
    debt_equity = (
        metrics.get("totalDebt/totalEquityAnnual") or
        metrics.get("longTermDebt/equityAnnual")
    )

    return {
        "ticker": ticker,
        "name": profile.get("name", ticker),
        "sector": sector,
        "market_cap": mc,
        "shares_outstanding": profile.get("shareOutstanding"),
        "beta": metrics.get("beta"),
        "revenue_growth": metrics.get("revenueGrowthTTMYoy"),
        "revenue_growth_q": rev_growth_q,
        "gross_margin": gross_margin_raw,
        "gross_margin_note": gross_margin_note,
        "operating_margin": metrics.get("operatingMarginTTM"),
        "net_margin": metrics.get("netProfitMarginTTM"),
        "fcf_margin": fcf_margin,
        "pe": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
        "ps": metrics.get("psTTM"),
        "roe": metrics.get("roeTTM"),
        "roic": roic,
        "debt_equity": debt_equity,
        "current_ratio": metrics.get("currentRatioAnnual"),
        "return_1y": metrics.get("52WeekPriceReturnDaily"),
        "return_6m": metrics.get("26WeekPriceReturnDaily"),
        "revenue_growth_annual": metrics.get("revenueGrowthAnnual"),
        "week52_high": metrics.get("52WeekHigh"),
        "week52_low": metrics.get("52WeekLow"),
    }




def _claude_dcf_commentary(d: dict) -> dict:
    """Ask Claude for DCF commentary only, never for numbers.

    Returns {"reasoning": ..., "confidence": ...} or {} on failure.
    Scenario parameters are mechanical; this text is labelled as
    commentary in the output and cannot move a price.
    """
    try:
        from services.claude_analyst import ClaudeAnalyst
        analyst = ClaudeAnalyst()
        profile = {
            "ticker": d.get("ticker"),
            "name": d.get("name"),
            "sector": d.get("sector"),
            "revenue_growth_pct": round(d.get("revenue_growth") or 0, 1),
            "gross_margin_pct": round(d.get("gross_margin") or 0, 1),
            "operating_margin_pct": round(d.get("operating_margin") or 0, 1),
            "net_margin_pct": round(d.get("net_margin") or 0, 1),
            "fcf_margin_pct": round(d.get("fcf_margin") or 0, 1),
            "pe": round(d.get("pe"), 1) if (d.get("pe") or 0) > 0 else None,
            "beta": round(d.get("beta") or 1, 2),
        }
        return analyst.explain_dcf_commentary(profile) or {}
    except Exception as e:
        logger.warning("Claude DCF commentary failed for %s: %s", d.get("ticker"), e)
        return {}


def _mechanial_scenarios(d: dict) -> dict:
    """
    Mechanical (non-Claude) bull/base/bear scenario parameters derived from fundamentals.
    Uses conservative 'sleeper' growth caps for mature/dividend stocks; switches to
    higher growth ceiling when TTM revenue growth > 20% (compounder-style stocks).
    Returns dict with bull/base/bear, each having g1/g2/fcf/tg keys.
    """
    rev_growth   = (d.get("revenue_growth") or 5) / 100
    fcf_margin   = (d.get("fcf_margin")     or 0) / 100
    gross_margin = (d.get("gross_margin")   or 40) / 100
    net_margin   = (d.get("net_margin")     or 0) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    if rev_growth > 0.20:  # high-growth: apply strong mean-reversion, hard caps at 30/18/10%
        return {
            "bull": {"g1": min(rev_growth * 0.70, 0.30), "g2": 0.12, "fcf": min(fcf_0 * 1.20, 0.45), "tg": 0.035},
            "base": {"g1": min(rev_growth * 0.45, 0.18), "g2": 0.08, "fcf": fcf_0,                    "tg": 0.030},
            "bear": {"g1": min(max(rev_growth * 0.15, 0.02), 0.10), "g2": 0.04, "fcf": fcf_0 * 0.70,  "tg": 0.020},
        }
    else:  # mature/dividend: conservative sleeper ceilings
        _g_bull = min(rev_growth * 1.3, 0.20)
        _g_base = min(rev_growth * 0.80, min(_g_bull, 0.12))
        _g_bear = min(max(rev_growth * 0.30, 0.02), _g_base)
        return {
            "bull": {"g1": _g_bull, "g2": 0.08, "fcf": min(fcf_0 * 1.20, 0.45), "tg": 0.030},
            "base": {"g1": _g_base, "g2": 0.05, "fcf": fcf_0,                    "tg": 0.025},
            "bear": {"g1": _g_bear, "g2": 0.03, "fcf": max(fcf_0 * 0.75, 0.01), "tg": 0.020},
        }


_SENSITIVITY_RATES = [0.055, 0.070, 0.085]


def _wacc_sensitivity(
    revenue_0: float,
    fcf_0: float,
    scenarios: dict,
    market_cap: float,
    shares_m: float,
    current_price: float | None,
) -> list[dict]:
    """Run DCF at 3 fixed WACC levels for sensitivity display. Same scenarios, different discount rates."""
    rows = []
    for test_dr in _SENSITIVITY_RATES:
        sens = _run_dcf(revenue_0, fcf_0, test_dr, scenarios, market_cap)
        row: dict = {"wacc_pct": round(test_dr * 100, 1)}
        for s in ("bull", "base", "bear"):
            up = sens.get(f"{s}_upside")
            price = (
                round(current_price * (1 + up / 100), 2)
                if (current_price and up is not None and shares_m > 0)
                else None
            )
            row[s] = {"price": price, "upside": up}
        rows.append(row)
    return rows



def _monte_carlo_dcf(
    revenue_0: float,
    market_cap: float,
    shares_m: float,
    dr: float,
    scenarios: dict,
    n: int = 10_000,
) -> dict:
    """
    Monte Carlo DCF: vectorised with numpy — all n simulations run as array ops.
    Draws g1/g2/fcf/dr from Normal(base, (bull-bear)/4) clipped to reasonable bounds.
    Returns intrinsic value distribution, per-share percentiles, and prob of undervaluation.
    """
    try:
        import numpy as np

        base = scenarios["base"]
        bull = scenarios["bull"]
        bear = scenarios["bear"]

        g1_mean = base["g1"]
        g1_std  = max((bull["g1"] - bear["g1"]) / 4, 0.01)
        g2_mean = base["g2"]
        g2_std  = max((bull["g2"] - bear["g2"]) / 4, 0.005)
        fm_mean = base["fm"]
        fm_std  = max((bull["fm"] - bear["fm"]) / 4, 0.01)
        tg_mean = base.get("tg", 0.025)

        rng = np.random.default_rng(42)
        g1_s = np.clip(rng.normal(g1_mean, g1_std, n), -0.30, 0.50)
        g2_s = np.clip(rng.normal(g2_mean, g2_std, n), -0.30, 0.60)
        fm_s = np.clip(rng.normal(fm_mean, fm_std, n), 0.01, 0.85)
        dr_s = np.clip(rng.normal(dr, 0.015, n), 0.05, 0.30)

        # Vectorised DCF — all n paths computed simultaneously
        rev = np.full(n, float(revenue_0))
        pv  = np.zeros(n)

        for yr in range(1, 6):
            rev = rev * (1.0 + g1_s)
            pv += (rev * fm_s) / (1.0 + dr_s) ** yr

        for yr in range(6, 11):
            rev = rev * (1.0 + g2_s)
            pv += (rev * fm_s) / (1.0 + dr_s) ** yr

        tg_s = np.minimum(tg_mean, dr_s - 0.005)
        terminal = rev * fm_s * (1.0 + tg_s) / (dr_s - tg_s) / (1.0 + dr_s) ** 10
        pvs = pv + terminal

        per_share = pvs / shares_m if shares_m > 0 else pvs

        counts, edges = np.histogram(per_share, bins=25)
        histogram = [{"x": round(float(edges[i]), 2), "count": int(counts[i])} for i in range(len(counts))]

        return {
            "n_simulations": n,
            "prob_undervalued_pct": round(float(np.mean(pvs > market_cap) * 100), 1),
            "per_share": {
                "p10":    round(float(np.percentile(per_share, 10)), 2),
                "p25":    round(float(np.percentile(per_share, 25)), 2),
                "median": round(float(np.median(per_share)), 2),
                "mean":   round(float(np.mean(per_share)), 2),
                "p75":    round(float(np.percentile(per_share, 75)), 2),
                "p90":    round(float(np.percentile(per_share, 90)), 2),
            },
            "histogram": histogram,
        }
    except Exception as e:
        logger.warning("Monte Carlo DCF failed: %s", e)
        return {}


def _safe_earnings_days(ticker: str) -> int | None:
    try:
        from services.finnhub_client import get_earnings_this_month
        return get_earnings_this_month(ticker)
    except Exception:
        return None


def analyze(ticker: str) -> dict:
    """
    Full DCF analysis for a single ticker.
    Returns a rich dict ready for the frontend, or raises ValueError on bad input.
    """
    ticker = ticker.upper().strip()
    d = _build_fundamentals(ticker)
    if not d:
        raise ValueError(f"No fundamentals available for {ticker}")

    market_cap = d["market_cap"]
    ps = d.get("ps") or 0
    net_margin = (d.get("net_margin") or 0) / 100
    pe_ratio = d.get("pe") or 0
    if ps > 0:
        revenue_0 = market_cap / ps
    elif pe_ratio > 0 and net_margin > 0:
        # P/S not available (banks, utilities, REITs): derive from P/E ÷ net margin
        revenue_0 = (market_cap / pe_ratio) / net_margin
    else:
        raise ValueError(f"No P/S ratio available for {ticker} — cannot derive revenue")

    # FCF floor
    fcf_margin = (d.get("fcf_margin") or 0) / 100
    gross_margin = (d.get("gross_margin") or 40) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    # Beta-derived WACC, debt-adjusted for non-financial companies with D/E > 0.5
    dr = _wacc_from_beta(
        beta=d.get("beta"),
        debt_equity_ratio=d.get("debt_equity") or 0,
        sector=d.get("sector"),
    )
    wacc_pct = round(dr * 100, 1)

    # Reverse DCF
    implied_growth_pct = _reverse_dcf(market_cap, revenue_0, fcf_0, dr)

    # Scenario parameters are mechanical only (_mechanial_scenarios,
    # same inputs every time). Claude is asked for commentary only,
    # and a commentary failure never changes the DCF prices.
    cp = _mechanial_scenarios(d)
    used_claude = False
    try:
        commentary = _claude_dcf_commentary(d)
    except Exception as e:
        logger.warning("Claude DCF commentary failed for %s: %s", d.get("ticker"), e)
        commentary = {}
    scenario_reasoning = commentary.get("reasoning", "")
    scenario_confidence = commentary.get("confidence", "")

    # No event-risk discount: it was a Claude-set number that moved
    # FCF margins and WACC, so it is out of the verdict math.
    event_risk_discount = 0.0
    event_risk_reason = None

    scenarios = {
        "bull": dict(g1=cp["bull"]["g1"], g2=cp["bull"]["g2"],
                     fm=cp["bull"]["fcf"], tg=cp["bull"].get("tg", 0.035)),
        "base": dict(g1=cp["base"]["g1"], g2=cp["base"]["g2"],
                     fm=cp["base"]["fcf"], tg=cp["base"].get("tg", 0.030)),
        "bear": dict(g1=cp["bear"]["g1"], g2=cp["bear"]["g2"],
                     fm=cp["bear"]["fcf"], tg=cp["bear"].get("tg", 0.020)),
    }

    dcf = _run_dcf(revenue_0, fcf_0, dr, scenarios, market_cap)

    # Per-share prices
    shares_m = d.get("shares_outstanding") or 0
    mc = _monte_carlo_dcf(revenue_0, market_cap, shares_m, dr, scenarios)
    current_price = None
    price_targets = {}
    if shares_m > 0:
        current_price = round(market_cap / shares_m, 2)
        for s in ("bull", "base", "bear"):
            upside = dcf.get(f"{s}_upside", 0)
            price_targets[s] = round(current_price * (1 + upside / 100), 2)

    base_up = dcf.get("base_upside", 0)
    if base_up >= 40:
        recommendation = "Strong Buy"
    elif base_up >= 15:
        recommendation = "Buy"
    elif base_up >= -10:
        recommendation = "Hold"
    else:
        recommendation = "Pass"

    return {
        "ticker": ticker,
        "name": d["name"],
        "sector": d["sector"],
        # Market context
        "market_cap_b": round(market_cap / 1000, 2),
        "current_price": current_price,
        "revenue_growth_pct": round(d.get("revenue_growth") or 0, 1),
        "gross_margin_pct": round(d.get("gross_margin") or 0, 1),
        "gross_margin_note": d.get("gross_margin_note", "reported"),
        "net_margin_pct": round(d.get("net_margin") or 0, 1),
        "fcf_margin_pct": round(max((d.get("fcf_margin") or 0) / 100, fcf_0) * 100, 1),
        "pe": round(d["pe"], 1) if (d.get("pe") or 0) > 0 else None,
        "ps": round(d["ps"], 1) if d.get("ps") else None,
        "beta": round(d["beta"], 2) if d.get("beta") else None,
        # ROIC / WACC spread
        "roic_pct": round(d["roic"], 1) if d.get("roic") is not None else None,
        "roic_wacc_spread_pct": round(d["roic"] - wacc_pct, 1) if d.get("roic") is not None else None,
        # DCF methodology
        "wacc_pct": wacc_pct,
        "implied_growth_pct": implied_growth_pct,
        "used_claude_params": used_claude,
        "scenario_reasoning": scenario_reasoning,
        "scenario_confidence": scenario_confidence,
        # Scenario parameters used (for transparency)
        "bull_g1_pct": round(scenarios["bull"]["g1"] * 100, 1),
        "base_g1_pct": round(scenarios["base"]["g1"] * 100, 1),
        "bear_g1_pct": round(scenarios["bear"]["g1"] * 100, 1),
        "bull_fcf_pct": round(scenarios["bull"]["fm"] * 100, 1),
        "base_fcf_pct": round(scenarios["base"]["fm"] * 100, 1),
        "bear_fcf_pct": round(scenarios["bear"]["fm"] * 100, 1),
        # DCF outputs
        "dcf_bull": dcf.get("bull"),
        "dcf_base": dcf.get("base"),
        "dcf_bear": dcf.get("bear"),
        "dcf_bull_upside": dcf.get("bull_upside"),
        "dcf_base_upside": dcf.get("base_upside"),
        "dcf_bear_upside": dcf.get("bear_upside"),
        "dcf_bull_price": price_targets.get("bull"),
        "dcf_base_price": price_targets.get("base"),
        "dcf_bear_price": price_targets.get("bear"),
        "recommendation": recommendation,
        "monte_carlo": mc,
        # Paradigm factors: retired as Claude inputs. The trigger
        # service now scores these from written quant rules instead,
        # so they are None here and never enter the DCF math.
        "platform_lock_in": None,
        "tam_expanding": None,
        "network_effects": None,
        "revenue_growth_annual_pct": round(d["revenue_growth_annual"], 1) if d.get("revenue_growth_annual") is not None else None,
        # Event risk discount
        "event_risk_discount": round(event_risk_discount, 2) if event_risk_discount > 0 else None,
        "event_risk_reason": event_risk_reason,
        "wacc_sensitivity": _wacc_sensitivity(revenue_0, fcf_0, scenarios, market_cap, shares_m, current_price),
        # Price context
        "high_52w": d.get("week52_high"),
        "low_52w": d.get("week52_low"),
        "pct_below_52w_high": round(
            (d["week52_high"] - current_price) / d["week52_high"] * 100, 1
        ) if d.get("week52_high") and d["week52_high"] > 0 and current_price else None,
        # Earnings window (days until next earnings, or None if beyond 30-day window)
        "next_earnings_days": _safe_earnings_days(ticker),
    }


def analyze_quant(ticker: str) -> dict:
    """
    Quantitative-only DCF — identical to analyze() but skips the Claude call.
    Uses mechanical scenarios (_mechanial_scenarios) directly.
    Safe to call in bulk scan loops without incurring LLM latency or cost.
    """
    ticker = ticker.upper().strip()
    d = _build_fundamentals(ticker)
    if not d:
        raise ValueError(f"No fundamentals available for {ticker}")

    market_cap = d["market_cap"]
    ps = d.get("ps") or 0
    net_margin = (d.get("net_margin") or 0) / 100
    pe_ratio = d.get("pe") or 0
    if ps > 0:
        revenue_0 = market_cap / ps
    elif pe_ratio > 0 and net_margin > 0:
        # P/S not available (banks, utilities, REITs): derive from P/E ÷ net margin
        revenue_0 = (market_cap / pe_ratio) / net_margin
    else:
        raise ValueError(f"No P/S ratio available for {ticker}")

    fcf_margin = (d.get("fcf_margin") or 0) / 100
    gross_margin = (d.get("gross_margin") or 40) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    dr = _wacc_from_beta(
        beta=d.get("beta"),
        debt_equity_ratio=d.get("debt_equity") or 0,
        sector=d.get("sector"),
    )
    wacc_pct = round(dr * 100, 1)
    implied_growth_pct = _reverse_dcf(market_cap, revenue_0, fcf_0, dr)

    cp = _mechanial_scenarios(d)
    scenarios = {
        "bull": dict(g1=cp["bull"]["g1"], g2=cp["bull"]["g2"],
                     fm=cp["bull"]["fcf"], tg=cp["bull"].get("tg", 0.035)),
        "base": dict(g1=cp["base"]["g1"], g2=cp["base"]["g2"],
                     fm=cp["base"]["fcf"], tg=cp["base"].get("tg", 0.030)),
        "bear": dict(g1=cp["bear"]["g1"], g2=cp["bear"]["g2"],
                     fm=cp["bear"]["fcf"], tg=cp["bear"].get("tg", 0.020)),
    }

    dcf = _run_dcf(revenue_0, fcf_0, dr, scenarios, market_cap)
    shares_m = d.get("shares_outstanding") or 0
    mc = _monte_carlo_dcf(revenue_0, market_cap, shares_m, dr, scenarios)

    current_price = None
    price_targets = {}
    if shares_m > 0:
        current_price = round(market_cap / shares_m, 2)
        for s in ("bull", "base", "bear"):
            upside = dcf.get(f"{s}_upside", 0)
            price_targets[s] = round(current_price * (1 + upside / 100), 2)

    base_up = dcf.get("base_upside", 0)
    if base_up >= 40:
        recommendation = "Strong Buy"
    elif base_up >= 15:
        recommendation = "Buy"
    elif base_up >= -10:
        recommendation = "Hold"
    else:
        recommendation = "Pass"

    return {
        "ticker": ticker,
        "name": d["name"],
        "sector": d["sector"],
        "market_cap_b": round(market_cap / 1000, 2),
        "current_price": current_price,
        "revenue_growth_pct": round(d.get("revenue_growth") or 0, 1),
        "gross_margin_pct": round(d.get("gross_margin") or 0, 1),
        "gross_margin_note": d.get("gross_margin_note", "reported"),
        "net_margin_pct": round(d.get("net_margin") or 0, 1),
        "fcf_margin_pct": round(max((d.get("fcf_margin") or 0) / 100, fcf_0) * 100, 1),
        "pe": round(d["pe"], 1) if (d.get("pe") or 0) > 0 else None,
        "ps": round(d["ps"], 1) if d.get("ps") else None,
        "beta": round(d["beta"], 2) if d.get("beta") else None,
        "roic_pct": round(d["roic"], 1) if d.get("roic") is not None else None,
        "roic_wacc_spread_pct": round(d["roic"] - wacc_pct, 1) if d.get("roic") is not None else None,
        "wacc_pct": wacc_pct,
        "implied_growth_pct": implied_growth_pct,
        "used_claude_params": False,
        "scenario_reasoning": "",
        "scenario_confidence": "",
        "bull_g1_pct": round(scenarios["bull"]["g1"] * 100, 1),
        "base_g1_pct": round(scenarios["base"]["g1"] * 100, 1),
        "bear_g1_pct": round(scenarios["bear"]["g1"] * 100, 1),
        "bull_fcf_pct": round(scenarios["bull"]["fm"] * 100, 1),
        "base_fcf_pct": round(scenarios["base"]["fm"] * 100, 1),
        "bear_fcf_pct": round(scenarios["bear"]["fm"] * 100, 1),
        "dcf_bull": dcf.get("bull"),
        "dcf_base": dcf.get("base"),
        "dcf_bear": dcf.get("bear"),
        "dcf_bull_upside": dcf.get("bull_upside"),
        "dcf_base_upside": dcf.get("base_upside"),
        "dcf_bear_upside": dcf.get("bear_upside"),
        "dcf_bull_price": price_targets.get("bull"),
        "dcf_base_price": price_targets.get("base"),
        "dcf_bear_price": price_targets.get("bear"),
        "recommendation": recommendation,
        "monte_carlo": mc,
        "platform_lock_in": None,
        "tam_expanding": None,
        "network_effects": None,
        "revenue_growth_annual_pct": round(d["revenue_growth_annual"], 1) if d.get("revenue_growth_annual") is not None else None,
        "event_risk_discount": None,
        "event_risk_reason": None,
        "wacc_sensitivity": _wacc_sensitivity(revenue_0, fcf_0, scenarios, market_cap, shares_m, current_price),
    }
