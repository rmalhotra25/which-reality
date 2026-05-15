"""
Standalone DCF analysis service.

For a given ticker:
  1. Fetches fundamentals + beta from Finnhub
  2. Derives CAPM-based WACC from beta
  3. Computes reverse DCF (implied growth rate priced in at current market cap)
  4. Calls Claude to set bear / base / bull scenario parameters based on the
     company's actual competitive position and industry dynamics
  5. Runs forward 10-year FCF DCF and returns per-share price targets

This is the same model used in the discovery picks but with a dedicated
Claude call focused entirely on scenario-setting for one company.
"""
import json
import logging
import re

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

    return {
        "ticker": ticker,
        "name": profile.get("name", ticker),
        "sector": profile.get("finnhubIndustry", "Unknown"),
        "market_cap": mc,
        "shares_outstanding": profile.get("shareOutstanding"),
        "beta": metrics.get("beta"),
        "revenue_growth": metrics.get("revenueGrowthTTMYoy"),
        "revenue_growth_q": rev_growth_q,
        "gross_margin": metrics.get("grossMarginTTM"),
        "operating_margin": metrics.get("operatingMarginTTM"),
        "net_margin": metrics.get("netProfitMarginTTM"),
        "fcf_margin": fcf_margin,
        "pe": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
        "ps": metrics.get("psTTM"),
        "roe": metrics.get("roeTTM"),
        "roic": roic,
        "debt_equity": metrics.get("debtToEquityAnnual"),
        "current_ratio": metrics.get("currentRatioAnnual"),
        "return_1y": metrics.get("52WeekPriceReturnDaily"),
        "return_6m": metrics.get("26WeekPriceReturnDaily"),
    }


def _claude_dcf_params(d: dict, implied_growth_pct: float, wacc_pct: float, fcf_0: float = 0.0) -> dict:
    """
    Ask Claude to set bull / base / bear scenario parameters for this specific
    company based on industry knowledge, competitive position, and current metrics.
    Returns a dict of scenario params or {} on failure.
    """
    try:
        from services.claude_analyst import ClaudeAnalyst
        analyst = ClaudeAnalyst()

        rev_g = d.get("revenue_growth") or 0
        rev_q = d.get("revenue_growth_q")
        accel = ""
        if rev_q is not None:
            diff = rev_q - rev_g
            accel = f" (recent quarter: {round(rev_q, 1)}%, {'accelerating ↑' if diff > 3 else 'decelerating ↓' if diff < -3 else 'stable'})"

        profile_str = (
            f"Company: {d['name']} ({d['ticker']})\n"
            f"Sector: {d['sector']}\n"
            f"Market Cap: ${round((d.get('market_cap') or 0) / 1000, 1)}B\n"
            f"Revenue Growth (TTM): {round(rev_g, 1)}%{accel}\n"
            f"Gross Margin: {round(d.get('gross_margin') or 0, 1)}%\n"
            f"Operating Margin: {round(d.get('operating_margin') or 0, 1)}%\n"
            f"Net Margin: {round(d.get('net_margin') or 0, 1)}%\n"
            f"FCF Margin: {round(max((d.get('fcf_margin') or 0) / 100, fcf_0) * 100, 1)}%\n"
            f"P/E: {round(d.get('pe'), 1) if (d.get('pe') or 0) > 0 else 'n/a'}\n"
            f"P/S: {round(d.get('ps'), 1) if d.get('ps') else 'n/a'}\n"
            f"ROE: {round(d.get('roe') or 0, 1)}%\n"
            f"ROIC: {round(d.get('roic') or 0, 1)}%\n"
            f"Beta: {round(d.get('beta') or 1, 2)}\n"
            f"WACC (CAPM): {wacc_pct}%\n"
            f"Reverse DCF implied growth (priced in): {implied_growth_pct}%/yr\n"
            f"1-yr price return: {round(d.get('return_1y') or 0, 1)}%"
        )

        system = (
            "You are a buy-side equity analyst building a DCF model. "
            "Your job is to set realistic bear, base, and bull scenario inputs "
            "based on deep knowledge of the company's competitive position, "
            "industry dynamics, and comparable companies. "
            "Do NOT use mechanical multipliers of historical growth. "
            "Think about: What is the realistic TAM growth? Can this company "
            "take/defend share? Where will margins land at maturity given "
            "competition and cost structure? What could go wrong? "
            "Respond ONLY with a valid JSON object — no prose, no markdown."
        )

        user = (
            f"{profile_str}\n\n"
            "Set DCF scenario parameters for a 10-year model.\n"
            "g1 = annual revenue growth rate years 1-5 (decimal, e.g. 0.25 = 25%)\n"
            "g2 = annual revenue growth rate years 6-10 (decimal)\n"
            "fcf = steady-state FCF margin by year 10 (decimal)\n"
            "tg = terminal growth rate after year 10 (typically 0.02-0.035)\n\n"
            "Constraints: bull > base > bear for g1, g2, and fcf.\n"
            "Also return:\n"
            "- reasoning: 2-3 sentences explaining your key assumptions\n"
            "- confidence: 'high' | 'medium' | 'low' (data quality / predictability)\n\n"
            "Return JSON:\n"
            '{"bull":{"g1":0.35,"g2":0.18,"fcf":0.32,"tg":0.035},'
            '"base":{"g1":0.22,"g2":0.12,"fcf":0.26,"tg":0.030},'
            '"bear":{"g1":0.08,"g2":0.05,"fcf":0.18,"tg":0.020},'
            '"reasoning":"...","confidence":"medium"}'
        )

        raw = analyst._call(system, user, max_tokens=800)
        clean = re.sub(r'^```[a-z]*\n?', '', raw.strip(), flags=re.MULTILINE)
        clean = re.sub(r'\n?```$', '', clean.strip()).strip()
        parsed = json.loads(clean)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        logger.warning("Claude DCF params failed for %s: %s", d.get("ticker"), e)
        return {}


def _mechanial_scenarios(d: dict) -> dict:
    """Fallback mechanical scenarios when Claude call fails."""
    rev_growth = (d.get("revenue_growth") or 5) / 100
    fcf_margin = (d.get("fcf_margin") or 0) / 100
    gross_margin = (d.get("gross_margin") or 40) / 100
    net_margin = (d.get("net_margin") or 0) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    return {
        "bull": {"g1": min(rev_growth, 0.80),        "g2": 0.20, "fcf": min(fcf_0 * 1.30, 0.55), "tg": 0.035},
        "base": {"g1": min(rev_growth * 0.70, 0.50), "g2": 0.12, "fcf": fcf_0,                    "tg": 0.030},
        "bear": {"g1": max(rev_growth * 0.30, 0.03), "g2": 0.05, "fcf": fcf_0 * 0.75,             "tg": 0.020},
    }


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
        g1_s = np.clip(rng.normal(g1_mean, g1_std, n), -0.30, 1.50)
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
    if ps <= 0:
        raise ValueError(f"No P/S ratio available for {ticker} — cannot derive revenue")

    revenue_0 = market_cap / ps

    # FCF floor
    fcf_margin = (d.get("fcf_margin") or 0) / 100
    gross_margin = (d.get("gross_margin") or 40) / 100
    net_margin = (d.get("net_margin") or 0) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    # Beta-derived WACC
    dr = _wacc_from_beta(d.get("beta"))
    wacc_pct = round(dr * 100, 1)

    # Reverse DCF
    implied_growth_pct = _reverse_dcf(market_cap, revenue_0, fcf_0, dr)

    # Claude scenario params — pass fcf_0 so the prompt shows a floor FCF even when Finnhub's field is empty
    cp = _claude_dcf_params(d, implied_growth_pct, wacc_pct, fcf_0=fcf_0)
    used_claude = bool(cp and "bull" in cp and "base" in cp and "bear" in cp)
    if not used_claude:
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
        "net_margin_pct": round(d.get("net_margin") or 0, 1),
        "fcf_margin_pct": round(max((d.get("fcf_margin") or 0) / 100, fcf_0) * 100, 1),
        "pe": round(d["pe"], 1) if (d.get("pe") or 0) > 0 else None,
        "ps": round(d["ps"], 1) if d.get("ps") else None,
        "beta": round(d["beta"], 2) if d.get("beta") else None,
        # DCF methodology
        "wacc_pct": wacc_pct,
        "implied_growth_pct": implied_growth_pct,
        "used_claude_params": used_claude,
        "scenario_reasoning": cp.get("reasoning", ""),
        "scenario_confidence": cp.get("confidence", ""),
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
    if ps <= 0:
        raise ValueError(f"No P/S ratio available for {ticker}")

    revenue_0 = market_cap / ps

    fcf_margin = (d.get("fcf_margin") or 0) / 100
    gross_margin = (d.get("gross_margin") or 40) / 100
    net_margin = (d.get("net_margin") or 0) / 100
    fcf_0 = max(fcf_margin, net_margin * 0.85, gross_margin * 0.15)

    dr = _wacc_from_beta(d.get("beta"))
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
        "net_margin_pct": round(d.get("net_margin") or 0, 1),
        "fcf_margin_pct": round(max((d.get("fcf_margin") or 0) / 100, fcf_0) * 100, 1),
        "pe": round(d["pe"], 1) if (d.get("pe") or 0) > 0 else None,
        "ps": round(d["ps"], 1) if d.get("ps") else None,
        "beta": round(d["beta"], 2) if d.get("beta") else None,
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
    }
