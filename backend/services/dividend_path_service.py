"""
Dividend Income Path - builds a safety-first dividend portfolio and projects
the DRIP + DCA compound path to $1,000/month passive income.

Projection is capped at 10 years, uses total-return-consistent math (price and
dividends grow at the same rate, so yield stays flat), lets negative dividend
growth through, and returns a bear case plus a labeled assumptions block.

Portfolio Universe: curated Dividend Aristocrats, quality dividend ETFs, REITs
Scoring (0-100):
  Yield Safety    : 30 pts  (yield high enough to matter, not so high it's a trap)
  Dividend Growth : 25 pts  (5Y CAGR of distributions)
  Price Stability : 20 pts  (low drawdown proxy from 52W range)
  Income Coverage : 15 pts  (years of consistent payments)
  Diversification : 10 pts  (category bonus - ensures mix of ETF/stock/REIT)

Cache: persistent scan_cache table in the app database (Postgres on Render,
SQLite locally), 6-hour TTL. The old /tmp file cache was wiped on every
Render redeploy, so the Income tab timed out after a deploy (Oct 27 2026).
"""
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE_TTL = 6 * 3600
_CACHE_KEY_PREFIX = "dividend_path"

from services.scan_cache import get_cache, set_cache


def _cache_key(starting_capital: float, weekly_dca: float) -> str:
    return f"{_CACHE_KEY_PREFIX}:{starting_capital:g}:{weekly_dca:g}"


def peek_cached(starting_capital: float = 61000.0, weekly_dca: float = 500.0) -> dict | None:
    """Return the cached dividend-path result for these params, or None."""
    return get_cache(_cache_key(starting_capital, weekly_dca), _CACHE_TTL)


def peek_any_cached() -> dict | None:
    """Return any cached dividend-path result, whatever its params were.

    The portfolio selection does not depend on starting capital or DCA, only
    the projection does, so a cached portfolio can be re-projected for a
    different monthly contribution without a rescan.
    """
    try:
        from database import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload FROM scan_cache"
                    " WHERE cache_key LIKE :p ORDER BY cached_at DESC LIMIT 1"
                ),
                {"p": f"{_CACHE_KEY_PREFIX}:%"},
            ).fetchall()
        if not rows:
            return None
        payload = json.loads(rows[0][0])
        if time.time() - float(payload.get("cached_at", 0)) > _CACHE_TTL:
            return None
        return payload
    except Exception as e:
        logger.warning("dividend_path peek_any_cached failed: %s", e)
        return None


def project_from_cached(starting_capital: float, monthly_contribution: float) -> dict | None:
    """Re-project the cached portfolio for a new monthly contribution.

    Uses the backend projection model (_build_projection) exactly, with the
    same base and bear assumptions as the cached scan. Returns None when no
    cached portfolio exists, so the caller can start a background scan.
    """
    cached = peek_any_cached()
    if not cached or not cached.get("portfolio"):
        return None
    portfolio = cached["portfolio"]
    weekly_dca = float(monthly_contribution) * 12 / 52
    scenarios = _build_projection(portfolio, starting_capital, weekly_dca)
    total_alloc = sum(s["allocation_pct"] for s in portfolio) or 100
    blended_yield = sum(s["annual_yield_pct"] * s["allocation_pct"] / total_alloc for s in portfolio)
    return {
        "scanned_at": cached.get("scanned_at"),
        "portfolio": portfolio,
        "params": {
            "starting_capital": starting_capital,
            "weekly_dca": round(weekly_dca, 2),
            "monthly_contribution": round(float(monthly_contribution), 2),
        },
        "blended_yield_pct": round(blended_yield, 2),
        "starting_monthly_income": round(starting_capital * (blended_yield / 100) / 12, 2),
        "goal_monthly_income": 1000.0,
        "reached_goal_at": scenarios["reached_goal_at"],
        "reached_goal_at_2000": scenarios["reached_goal_at_2000"],
        "projection": scenarios["projection"],
        "reached_goal_at_bear": scenarios["reached_goal_at_bear"],
        "reached_goal_at_bear_2000": scenarios["reached_goal_at_bear_2000"],
        "projection_bear": scenarios["projection_bear"],
        "projection_assumptions": scenarios["projection_assumptions"],
    }

# Curated universe: Aristocrats + quality dividend ETFs + REITs
# Categorized for diversification scoring
_UNIVERSE = {
    # Blue-chip Dividend Aristocrats / Kings
    "JNJ":  {"category": "aristocrat", "name": "Johnson & Johnson"},
    "KO":   {"category": "aristocrat", "name": "Coca-Cola"},
    "PG":   {"category": "aristocrat", "name": "Procter & Gamble"},
    "MMM":  {"category": "aristocrat", "name": "3M"},
    "ABT":  {"category": "aristocrat", "name": "Abbott Labs"},
    "MCD":  {"category": "aristocrat", "name": "McDonald's"},
    "CL":   {"category": "aristocrat", "name": "Colgate-Palmolive"},
    "WMT":  {"category": "aristocrat", "name": "Walmart"},
    "ITW":  {"category": "aristocrat", "name": "Illinois Tool Works"},
    "EMR":  {"category": "aristocrat", "name": "Emerson Electric"},
    "AFL":  {"category": "aristocrat", "name": "Aflac"},
    "ADP":  {"category": "aristocrat", "name": "ADP"},
    "T":    {"category": "aristocrat", "name": "AT&T"},
    "VZ":   {"category": "aristocrat", "name": "Verizon"},
    "LOW":  {"category": "aristocrat", "name": "Lowe's"},
    "GPC":  {"category": "aristocrat", "name": "Genuine Parts"},
    "BEN":  {"category": "aristocrat", "name": "Franklin Resources"},
    "NUE":  {"category": "aristocrat", "name": "Nucor"},
    "CINF": {"category": "aristocrat", "name": "Cincinnati Financial"},
    "SWK":  {"category": "aristocrat", "name": "Stanley Black & Decker"},
    # High-quality dividend ETFs
    "VYM":  {"category": "etf", "name": "Vanguard High Div Yield ETF"},
    "SCHD": {"category": "etf", "name": "Schwab US Dividend Equity ETF"},
    "DVY":  {"category": "etf", "name": "iShares Div Select ETF"},
    "HDV":  {"category": "etf", "name": "iShares Core High Div ETF"},
    "SDY":  {"category": "etf", "name": "SPDR S&P Dividend ETF"},
    "DGRO": {"category": "etf", "name": "iShares Dividend Growth ETF"},
    "VIG":  {"category": "etf", "name": "Vanguard Dividend Appreciation ETF"},
    "NOBL": {"category": "etf", "name": "ProShares S&P 500 Div Aristocrats"},
    "SPYD": {"category": "etf", "name": "SPDR Portfolio S&P 500 High Div"},
    "FDVV": {"category": "etf", "name": "Fidelity High Dividend ETF"},
    # REITs - income generators
    "O":    {"category": "reit", "name": "Realty Income"},
    "NNN":  {"category": "reit", "name": "National Retail Properties"},
    "STAG": {"category": "reit", "name": "STAG Industrial"},
    "WPC":  {"category": "reit", "name": "W. P. Carey"},
    "ADC":  {"category": "reit", "name": "Agree Realty"},
    "MAIN": {"category": "reit", "name": "Main Street Capital"},
    "EPR":  {"category": "reit", "name": "EPR Properties"},
    "LTC":  {"category": "reit", "name": "LTC Properties"},
}

# Allocation targets by category (how much weight each category gets)
_CATEGORY_TARGET_WEIGHTS = {
    "etf":        0.45,   # Core ETFs for stability + broad exposure
    "aristocrat": 0.35,   # Blue chips for dividend growth
    "reit":       0.20,   # REITs for income
}

# Per-holding max weight
_MAX_SINGLE_WEIGHT = 0.25


def _get_price_data(ticker: str) -> dict:
    """Close prices → price, 52W range, 6M-ago price."""
    try:
        from services.polygon_client import get_close_prices
        closes = get_close_prices(ticker, days=380)
        if not closes:
            return {}
        price = closes[-1]
        window = closes[-252:] if len(closes) >= 252 else closes
        return {
            "price": price,
            "high_52w": max(window),
            "low_52w": min(window),
            "price_6m_ago": closes[-126] if len(closes) >= 126 else closes[0],
            "price_1y_ago": closes[-252] if len(closes) >= 252 else closes[0],
        }
    except Exception as e:
        logger.debug("price_data failed for %s: %s", ticker, e)
        return {}


def _compute_ttm_div_growth(payments: list[tuple[date, float]], as_of: date) -> float:
    """Annualized dividend growth from trailing-12-month totals.

    payments is a list of (ex_date, amount) pairs. Growth compares the sum of
    payments in the trailing 12 months against the sum in the prior 12 months,
    annualized only over the actual elapsed months between the midpoints of
    the two windows. Because both windows are fixed 12-month sums, a quarterly
    payer and a monthly payer with the same true growth get the same number.
    Returns 0.0 when either window is empty. Clamped to -50%..+50%.
    """
    ttm = [(d, a) for d, a in payments if 0 <= (as_of - d).days <= 365]
    prior = [(d, a) for d, a in payments if 365 < (as_of - d).days <= 730]
    ttm_sum = sum(a for _, a in ttm)
    prior_sum = sum(a for _, a in prior)
    if not ttm or not prior or ttm_sum <= 0 or prior_sum <= 0:
        return 0.0
    mid_ttm = date.fromordinal(sum(d.toordinal() for d, _ in ttm) // len(ttm))
    mid_prior = date.fromordinal(sum(d.toordinal() for d, _ in prior) // len(prior))
    elapsed_months = (mid_ttm - mid_prior).days / 30.4375
    if elapsed_months <= 0:
        return 0.0
    growth = (ttm_sum / prior_sum) ** (12.0 / elapsed_months) - 1
    return round(max(-0.50, min(growth, 0.50)) * 100, 1)


def _get_dividend_data(ticker: str) -> dict:
    """Dividend history from Polygon: trailing-12-month yield, growth, streak."""
    try:
        from services.polygon_client import _client
        c = _client()
        # 800 days so both the trailing-12-month window and the prior 12 months
        # are covered for the growth comparison.
        ex_from = (date.today() - timedelta(days=800)).isoformat()
        items = list(c.list_dividends(
            ticker=ticker,
            ex_dividend_date_gte=ex_from,
            limit=100,
            order="desc",
        ))
        if not items:
            return {}

        divs = [
            {
                "ex_date": str(getattr(d, "ex_dividend_date", "") or ""),
                "amount": float(getattr(d, "cash_amount", 0) or 0),
                "frequency": int(getattr(d, "frequency", 4) or 4),
            }
            for d in items
        ]

        today = date.today()
        dated: list[tuple[date, float]] = []
        for d in divs:
            try:
                parsed = date.fromisoformat(d["ex_date"]) if d["ex_date"] else None
            except ValueError:
                parsed = None
            if parsed is not None and d["amount"] > 0:
                dated.append((parsed, d["amount"]))

        recent = divs[0]
        frequency = recent["frequency"] or 4

        # Annual dividend is the trailing-12-month sum, not one payment times
        # frequency, so monthly and quarterly payers are measured the same way.
        ttm_sum = sum(a for d, a in dated if 0 <= (today - d).days <= 365)
        if ttm_sum > 0:
            annual_div = ttm_sum
        else:
            annual_div = recent["amount"] * frequency

        # Streak: non-zero payments in the last 400 days (unchanged window,
        # so the income-coverage scoring bands keep their meaning).
        streak = sum(1 for d, a in dated if 0 <= (today - d).days <= 400)

        div_growth_pct = _compute_ttm_div_growth(dated, today)

        return {
            "recent_div": recent["amount"],
            "frequency": frequency,
            "annual_div": annual_div,
            "streak_payments": streak,
            "div_growth_pct": div_growth_pct,
        }
    except Exception as e:
        logger.debug("div_data failed for %s: %s", ticker, e)
        return {}


def _score_ticker(ticker: str, meta: dict, snap: dict, div: dict) -> dict | None:
    """Score a ticker 0-100 for the dividend income path."""
    price = snap.get("price", 0)
    if price <= 0:
        return None

    annual_div = div.get("annual_div", 0)
    annual_yield_pct = (annual_div / price * 100) if annual_div and price > 0 else 0

    score = 0
    breakdown = {}

    # 1. Yield Safety (30 pts) - too low = not enough income, too high = danger
    if 3.5 <= annual_yield_pct < 6.0:
        ys = 30   # Sweet spot
    elif 2.5 <= annual_yield_pct < 3.5:
        ys = 22   # Good for growth-oriented
    elif 6.0 <= annual_yield_pct < 9.0:
        ys = 18   # High yield, monitor for safety
    elif annual_yield_pct >= 9.0:
        ys = 8    # Very high - probable risk
    elif annual_yield_pct >= 1.5:
        ys = 10   # Low but growing
    else:
        ys = 0
    score += ys
    breakdown["yield_safety"] = ys

    # 2. Dividend Growth (25 pts)
    dg = div.get("div_growth_pct", 0)
    if dg >= 8:
        dgp = 25
    elif dg >= 5:
        dgp = 20
    elif dg >= 2:
        dgp = 14
    elif dg >= 0:
        dgp = 8
    else:
        dgp = 2   # Dividend cut - penalize
    score += dgp
    breakdown["div_growth"] = dgp

    # 3. Price Stability (20 pts) - how far from 52W high (drawdown proxy)
    high_52w = snap.get("high_52w", price)
    if high_52w > 0:
        drawdown_pct = (high_52w - price) / high_52w * 100
        if drawdown_pct <= 5:
            ps = 20
        elif drawdown_pct <= 12:
            ps = 16
        elif drawdown_pct <= 20:
            ps = 11
        elif drawdown_pct <= 30:
            ps = 6
        else:
            ps = 2
    else:
        ps = 8
    score += ps
    breakdown["price_stability"] = ps

    # 4. Income Coverage (15 pts) - number of consecutive dividend payments
    streak = div.get("streak_payments", 0)
    if streak >= 20:
        ic = 15
    elif streak >= 12:
        ic = 12
    elif streak >= 8:
        ic = 8
    elif streak >= 4:
        ic = 4
    else:
        ic = 1
    score += ic
    breakdown["income_coverage"] = ic

    # 5. Category bonus applied at portfolio level for diversification
    breakdown["category_bonus"] = 0

    return {
        "ticker": ticker,
        "category": meta["category"],
        "name": meta["name"],
        "score": min(score, 100),
        "price": round(price, 2),
        "annual_yield_pct": round(annual_yield_pct, 2),
        "annual_div": round(annual_div, 4),
        "monthly_div_per_share": round(annual_div / 12, 4),
        "frequency": div.get("frequency", 4),
        "recent_div": round(div.get("recent_div", 0), 4),
        "streak_payments": streak,
        "div_growth_pct": div.get("div_growth_pct", 0),
        "high_52w": round(snap.get("high_52w", price), 2),
        "low_52w": round(snap.get("low_52w", price), 2),
        "drawdown_from_high_pct": round((snap.get("high_52w", price) - price) / max(snap.get("high_52w", price), 1) * 100, 1),
        "score_breakdown": breakdown,
    }


def _select_portfolio(scored: list[dict]) -> list[dict]:
    """
    Pick 6 holdings that balance category targets and individual quality.
    Allocations are set by the tool, not the user.
    """
    # Sort by score within each category
    by_cat: dict[str, list] = {"etf": [], "aristocrat": [], "reit": []}
    for s in scored:
        cat = s.get("category", "aristocrat")
        if cat in by_cat:
            by_cat[cat].append(s)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["score"], reverse=True)

    # Select: 2 ETFs, 2-3 Aristocrats, 1-2 REITs (6 total)
    selected = []
    selected.extend(by_cat["etf"][:2])
    selected.extend(by_cat["aristocrat"][:2])
    selected.extend(by_cat["reit"][:2])

    # If any category is short, fill with next-best from others
    if len(selected) < 6:
        used = {s["ticker"] for s in selected}
        for cat in ["etf", "aristocrat", "reit"]:
            for s in by_cat[cat]:
                if len(selected) >= 6:
                    break
                if s["ticker"] not in used:
                    selected.append(s)
                    used.add(s["ticker"])

    # Assign allocations based on category target weights + score weighting
    # ETFs get ~45%, Aristocrats ~35%, REITs ~20%, normalized
    cat_counts = {}
    for s in selected:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1

    alloc_weights = []
    for s in selected:
        cat = s["category"]
        n = cat_counts.get(cat, 1)
        weight = _CATEGORY_TARGET_WEIGHTS.get(cat, 0.20) / n
        alloc_weights.append(weight)

    # Normalize to sum to 1.0
    total_w = sum(alloc_weights)
    alloc_weights = [w / total_w for w in alloc_weights]

    # Assign and round to nearest 5%
    for i, s in enumerate(selected):
        raw_pct = alloc_weights[i] * 100
        s["allocation_pct"] = round(raw_pct / 5) * 5

    # Fix rounding drift → ensure sum is exactly 100
    total_alloc = sum(s["allocation_pct"] for s in selected)
    diff = 100 - total_alloc
    if diff != 0:
        # Add difference to highest-weight ETF or first holding
        selected[0]["allocation_pct"] += diff

    return selected


def _run_projection(
    starting_capital: float,
    weekly_dca: float,
    blended_yield: float,
    avg_div_growth_pct: float,
    months: int = 120,
) -> tuple[list[dict], dict | None, dict | None]:
    """DRIP + DCA projection, capped at 10 years (120 months).

    Total-return-consistent share model: price and the dividend per share both
    grow at the dividend-growth rate, so the yield stays flat and the total
    return is dividend growth plus yield. Dividends are reinvested (DRIP) and
    the weekly DCA buys shares at the current price. Negative dividend growth
    is allowed through: no floor, so a shrinking dividend projects a shrinking
    income. Growth is clamped to -50%..+8% a year to bound absurd inputs.
    blended_yield is a decimal (e.g. 0.04). Price is normalized to $1, so the
    starting share count equals the starting capital.

    Returns snapshots plus the month $1,000/month and $2,000/month of
    dividend income are first reached, or None for a goal not reached.
    """
    months = max(1, min(int(months), 120))
    annual_div_growth = max(-0.50, min(avg_div_growth_pct / 100, 0.08))
    monthly_growth = (1 + annual_div_growth) ** (1 / 12) - 1
    monthly_contribution = weekly_dca * 52 / 12

    price = 1.0
    dps = blended_yield  # annual dividend per share on a $1 starting price
    shares = float(starting_capital)
    goal_monthly_income = 1000.0
    goal2_monthly_income = 2000.0
    snapshots = []
    reached_goal_at = None
    reached_goal_at_2000 = None

    for month in range(1, months + 1):
        price = price * (1 + monthly_growth)
        dps = dps * (1 + monthly_growth)
        shares += monthly_contribution / price  # DCA buys at the current price
        monthly_income = shares * dps / 12  # dividends on shares held
        shares += monthly_income / price  # DRIP reinvests the dividend
        portfolio_value = shares * price
        total_contributed = starting_capital + monthly_contribution * month

        year = (month - 1) // 12 + 1
        mo = (month - 1) % 12 + 1

        if month % 6 == 0 or month == 1 or monthly_income >= goal_monthly_income:
            snapshots.append({
                "month": month,
                "year": year,
                "month_of_year": mo,
                "portfolio_value": round(portfolio_value, 2),
                "monthly_income": round(monthly_income, 2),
                "annual_income": round(monthly_income * 12, 2),
                "total_contributed": round(total_contributed, 2),
                "growth": round(portfolio_value - total_contributed, 2),
                "yield_on_cost": round(monthly_income * 12 / total_contributed * 100, 3) if total_contributed > 0 else 0.0,
            })

        if monthly_income >= goal_monthly_income and reached_goal_at is None:
            reached_goal_at = {"month": month, "year": year, "month_label": f"Month {month}"}

        if monthly_income >= goal2_monthly_income and reached_goal_at_2000 is None:
            reached_goal_at_2000 = {"month": month, "year": year, "month_label": f"Month {month}"}

    return snapshots, reached_goal_at, reached_goal_at_2000


def _project_with_scenarios(
    starting_capital: float,
    weekly_dca: float,
    blended_yield: float,
    avg_div_growth_pct: float,
    months: int = 120,
) -> dict:
    """Base and bear-case projections with the assumptions labeled.

    Bear case: dividend and price growth 3 points lower than base. Both cases
    cap at 10 years and let negative growth through. The assumptions block is
    part of the output so the numbers are never shown without their limits:
    no bear market, no dividend cut beyond the growth rate shown, no fees,
    no taxes.
    """
    months = max(1, min(int(months), 120))
    base_snaps, base_goal, base_goal_2000 = _run_projection(
        starting_capital, weekly_dca, blended_yield, avg_div_growth_pct, months
    )
    bear_growth_pct = avg_div_growth_pct - 3.0
    bear_snaps, bear_goal, bear_goal_2000 = _run_projection(
        starting_capital, weekly_dca, blended_yield, bear_growth_pct, months
    )
    return {
        "projection": base_snaps,
        "reached_goal_at": base_goal,
        "reached_goal_at_2000": base_goal_2000,
        "projection_bear": bear_snaps,
        "reached_goal_at_bear": bear_goal,
        "reached_goal_at_bear_2000": bear_goal_2000,
        "projection_assumptions": {
            "horizon_months": months,
            "horizon_years": round(months / 12, 1),
            "starting_yield_pct": round(blended_yield * 100, 2),
            "base_dividend_growth_pct": round(avg_div_growth_pct, 1),
            "bear_dividend_growth_pct": round(bear_growth_pct, 1),
            "monthly_contribution": round(weekly_dca * 52 / 12, 2),
            "price_growth_note": "Price grows at the dividend-growth rate, so yield stays flat; total return is dividend growth plus yield.",
            "bear_case_note": "Bear case is dividend and price growth 3 points lower than base.",
            "excluded_note": "Assumes no bear market, no dividend cut beyond the growth rate shown, no fees, no taxes.",
        },
    }


def _build_projection(
    portfolio: list[dict],
    starting_capital: float,
    weekly_dca: float,
    months: int = 120,
) -> dict:
    """Build base and bear-case projections from a portfolio list weighted by allocation_pct."""
    total_alloc = sum(s["allocation_pct"] for s in portfolio) or 100
    blended_yield = sum(s["annual_yield_pct"] * s["allocation_pct"] / total_alloc for s in portfolio) / 100
    avg_div_growth = sum(s.get("div_growth_pct", 0) * s["allocation_pct"] / total_alloc for s in portfolio)
    return _project_with_scenarios(starting_capital, weekly_dca, blended_yield, avg_div_growth, months)


def run_custom_portfolio(
    holdings: list[dict],
    starting_capital: float = 61000.0,
    weekly_dca: float = 500.0,
) -> dict:
    """
    Fetch live data for a user-defined set of tickers, score them, and run the
    DRIP+DCA projection. Dollar amounts and DCA percentages are caller-supplied.
    """
    results = []
    errors = []

    for h in holdings:
        ticker = h["ticker"].upper().strip()
        dollar_amount = float(h.get("dollar_amount", 0))
        dca_pct = float(h.get("dca_pct", round(100 / max(len(holdings), 1), 1)))
        meta = _UNIVERSE.get(ticker, {"category": "custom", "name": ticker})

        try:
            snap = _get_price_data(ticker)
            div = _get_dividend_data(ticker)
            price = snap.get("price", 0)

            if price <= 0:
                results.append({
                    "ticker": ticker, "name": meta["name"], "category": meta["category"],
                    "dollar_amount": dollar_amount, "dca_pct": dca_pct,
                    "allocation_pct": round(dollar_amount / starting_capital * 100, 1) if starting_capital else 0,
                    "price": 0, "annual_yield_pct": 0, "annual_div": 0,
                    "monthly_div_per_share": 0, "score": 0, "div_growth_pct": 0,
                    "streak_payments": 0, "high_52w": 0, "low_52w": 0,
                    "drawdown_from_high_pct": 0, "error": "No price data",
                })
                errors.append(ticker)
                continue

            scored = _score_ticker(ticker, meta, snap, div) or {}
            scored["dollar_amount"] = dollar_amount
            scored["dca_pct"] = dca_pct
            scored["allocation_pct"] = round(dollar_amount / starting_capital * 100, 1) if starting_capital else 0
            results.append(scored)

        except Exception as e:
            logger.debug("custom portfolio error for %s: %s", ticker, e)
            errors.append(ticker)
            results.append({
                "ticker": ticker, "name": meta["name"], "category": meta["category"],
                "dollar_amount": dollar_amount, "dca_pct": dca_pct,
                "allocation_pct": round(dollar_amount / starting_capital * 100, 1) if starting_capital else 0,
                "price": 0, "annual_yield_pct": 0, "annual_div": 0,
                "monthly_div_per_share": 0, "score": 0, "div_growth_pct": 0,
                "streak_payments": 0, "high_52w": 0, "low_52w": 0,
                "drawdown_from_high_pct": 0, "error": str(e),
            })

        time.sleep(0.2)

    total_dollars = sum(r.get("dollar_amount", 0) for r in results) or starting_capital
    blended_yield = sum(
        r.get("annual_yield_pct", 0) * r.get("dollar_amount", 0) / total_dollars
        for r in results
    ) / 100
    avg_div_growth = sum(
        r.get("div_growth_pct", 0) * r.get("dollar_amount", 0) / total_dollars
        for r in results
    )

    scenarios = _project_with_scenarios(starting_capital, weekly_dca, blended_yield, avg_div_growth)

    return {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "portfolio": results,
        "errors": errors,
        "params": {
            "starting_capital": starting_capital,
            "weekly_dca": weekly_dca,
            "monthly_contribution": round(weekly_dca * 52 / 12, 2),
        },
        "blended_yield_pct": round(blended_yield * 100, 2),
        "starting_monthly_income": round(starting_capital * blended_yield / 12, 2),
        "goal_monthly_income": 1000.0,
        "reached_goal_at": scenarios["reached_goal_at"],
        "reached_goal_at_2000": scenarios["reached_goal_at_2000"],
        "projection": scenarios["projection"],
        "reached_goal_at_bear": scenarios["reached_goal_at_bear"],
        "reached_goal_at_bear_2000": scenarios["reached_goal_at_bear_2000"],
        "projection_bear": scenarios["projection_bear"],
        "projection_assumptions": scenarios["projection_assumptions"],
    }


def _distribute_lump_sum(
    portfolio: list[dict],
    lump_amount: float,
) -> list[dict]:
    """Distribute a lump sum addition across the portfolio per existing allocations."""
    result = []
    for s in portfolio:
        alloc_pct = s["allocation_pct"] / 100
        amount = round(lump_amount * alloc_pct, 2)
        price = s["price"]
        shares = round(amount / price, 4) if price > 0 else 0
        result.append({
            "ticker": s["ticker"],
            "name": s["name"],
            "category": s["category"],
            "allocation_pct": s["allocation_pct"],
            "lump_amount": amount,
            "shares_to_buy": shares,
            "price": price,
            "annual_yield_pct": s["annual_yield_pct"],
            "added_monthly_income": round(shares * s["annual_div"] / 12, 2),
        })
    return result


def build_dividend_path(
    starting_capital: float = 61000.0,
    weekly_dca: float = 500.0,
    force: bool = False,
) -> dict:
    """
    Main entry point: scan universe, select portfolio, project income path.
    Results cached for 6 hours in the persistent scan_cache table.
    """
    if not force:
        cached = peek_cached(starting_capital, weekly_dca)
        if cached:
            logger.info("dividend_path: returning cached results")
            return cached

    _scan_started_at = datetime.now(timezone.utc)
    scored_all = []
    errors = []
    for ticker, meta in _UNIVERSE.items():
        try:
            snap = _get_price_data(ticker)
            if not snap or snap.get("price", 0) <= 0:
                errors.append(ticker)
                continue
            div = _get_dividend_data(ticker)
            if not div or div.get("annual_div", 0) <= 0:
                errors.append(ticker)
                continue
            result = _score_ticker(ticker, meta, snap, div)
            if result:
                scored_all.append(result)
        except Exception as e:
            errors.append(ticker)
            logger.debug("dividend_path score error for %s: %s", ticker, e)
        time.sleep(0.2)

    if not scored_all:
        raise RuntimeError("No dividend data available - check API keys")

    scored_all.sort(key=lambda x: x["score"], reverse=True)
    portfolio = _select_portfolio(scored_all)

    scenarios = _build_projection(portfolio, starting_capital, weekly_dca)

    # Blended stats
    total_alloc = sum(s["allocation_pct"] for s in portfolio) or 100
    blended_yield = sum(s["annual_yield_pct"] * s["allocation_pct"] / total_alloc for s in portfolio)
    starting_monthly_income = starting_capital * (blended_yield / 100) / 12

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "universe_count": len(_UNIVERSE),
        "scored_count": len(scored_all),
        "errors": errors,
        "portfolio": portfolio,
        "params": {
            "starting_capital": starting_capital,
            "weekly_dca": weekly_dca,
            "monthly_contribution": round(weekly_dca * 52 / 12, 2),
        },
        "blended_yield_pct": round(blended_yield, 2),
        "starting_monthly_income": round(starting_monthly_income, 2),
        "goal_monthly_income": 1000.0,
        "reached_goal_at": scenarios["reached_goal_at"],
        "reached_goal_at_2000": scenarios["reached_goal_at_2000"],
        "projection": scenarios["projection"],
        "reached_goal_at_bear": scenarios["reached_goal_at_bear"],
        "reached_goal_at_bear_2000": scenarios["reached_goal_at_bear_2000"],
        "projection_bear": scenarios["projection_bear"],
        "projection_assumptions": scenarios["projection_assumptions"],
        "top_candidates": scored_all[:15],
    }
    set_cache(_cache_key(starting_capital, weekly_dca), output)
    logger.info("dividend_path complete: %d scored, portfolio of %d", len(scored_all), len(portfolio))
    # Persistent run receipt (P1). A cache hit above returns early with
    # no receipt: no new run happened, the original scan's receipt stands.
    try:
        from database import SessionLocal
        from services.run_receipts import write_receipt, JOB_DIVIDEND_PATH
        _db = SessionLocal()
        try:
            write_receipt(
                _db, JOB_DIVIDEND_PATH, _scan_started_at, "ok",
                tickers_evaluated=len(_UNIVERSE),
                alerts_fired=len(portfolio),
                suppressed=len(errors),
                errors=errors[:50],
            )
        finally:
            _db.close()
    except Exception as e:
        logger.warning("dividend_path: receipt write failed: %s", e)
    return output
