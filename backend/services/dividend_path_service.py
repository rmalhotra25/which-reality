"""
Dividend Income Path — builds a safety-first dividend portfolio and projects
the DRIP + DCA compound path to $1,000/month passive income.

Portfolio Universe: curated Dividend Aristocrats, quality dividend ETFs, REITs
Scoring (0-100):
  Yield Safety    : 30 pts  (yield high enough to matter, not so high it's a trap)
  Dividend Growth : 25 pts  (5Y CAGR of distributions)
  Price Stability : 20 pts  (low drawdown proxy from 52W range)
  Income Coverage : 15 pts  (years of consistent payments)
  Diversification : 10 pts  (category bonus — ensures mix of ETF/stock/REIT)

Cache TTL: 6 hours
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE_FILE = "/tmp/cache_dividend_path.json"
_CACHE_TTL = 6 * 3600

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
    # REITs — income generators
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


def _get_dividend_data(ticker: str) -> dict:
    """Dividend history from Polygon → annual yield, growth, streak."""
    try:
        from services.polygon_client import _client
        c = _client()
        ex_from = (date.today() - timedelta(days=400)).isoformat()
        items = list(c.list_dividends(
            ticker=ticker,
            ex_dividend_date_gte=ex_from,
            limit=50,
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

        recent = divs[0]
        frequency = recent["frequency"] or 4
        annual_div = recent["amount"] * frequency

        # Streak: consecutive non-zero payments
        streak = sum(1 for d in divs if d["amount"] > 0)

        # Div growth: compare recent annual rate vs ~12 payments ago
        older = divs[min(11, len(divs) - 1)]
        older_annual = older["amount"] * (older["frequency"] or 4)
        if older_annual > 0 and annual_div > 0:
            div_growth_pct = ((annual_div / older_annual) ** (12 / max(streak, 1)) - 1) * 100
            div_growth_pct = round(max(-50, min(div_growth_pct, 50)), 1)
        else:
            div_growth_pct = 0.0

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

    # 1. Yield Safety (30 pts) — too low = not enough income, too high = danger
    if 3.5 <= annual_yield_pct < 6.0:
        ys = 30   # Sweet spot
    elif 2.5 <= annual_yield_pct < 3.5:
        ys = 22   # Good for growth-oriented
    elif 6.0 <= annual_yield_pct < 9.0:
        ys = 18   # High yield, monitor for safety
    elif annual_yield_pct >= 9.0:
        ys = 8    # Very high — probable risk
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
        dgp = 2   # Dividend cut — penalize
    score += dgp
    breakdown["div_growth"] = dgp

    # 3. Price Stability (20 pts) — how far from 52W high (drawdown proxy)
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

    # 4. Income Coverage (15 pts) — number of consecutive dividend payments
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


def _build_projection(
    portfolio: list[dict],
    starting_capital: float,
    weekly_dca: float,
    months: int = 360,
) -> list[dict]:
    """
    Month-by-month DRIP + DCA projection.
    Returns list of monthly snapshots until $1,000/month goal or end of horizon.
    """
    # Blended portfolio yield and avg dividend growth
    total_alloc = sum(s["allocation_pct"] for s in portfolio) or 100
    blended_yield = sum(s["annual_yield_pct"] * s["allocation_pct"] / total_alloc for s in portfolio) / 100
    avg_div_growth = sum(s["div_growth_pct"] * s["allocation_pct"] / total_alloc for s in portfolio) / 100

    # Conservative assumptions
    # Price appreciation: ETF-heavy portfolio ~5-6% annually, we use 5%
    annual_price_appreciation = 0.05
    # Dividend growth bounded conservatively
    annual_div_growth = max(0.02, min(avg_div_growth / 100, 0.08))
    # Total annual return = price appreciation + yield (for DRIP reinvestment)
    annual_total_return = annual_price_appreciation + blended_yield
    monthly_total_return = annual_total_return / 12
    monthly_div_growth = (1 + annual_div_growth) ** (1 / 12) - 1

    monthly_contribution = weekly_dca * 52 / 12  # ~$2,166.67/month

    portfolio_value = starting_capital
    current_yield = blended_yield  # tracks as dividends grow
    goal_monthly_income = 1000.0

    snapshots = []
    reached_goal_at = None

    for month in range(1, months + 1):
        # Monthly income from dividends
        monthly_income = portfolio_value * current_yield / 12

        # DRIP: reinvest dividends + add DCA contribution
        portfolio_value = portfolio_value * (1 + monthly_total_return) + monthly_contribution

        # Dividend yield on invested capital grows as dividends grow
        current_yield = current_yield * (1 + monthly_div_growth)

        monthly_income_after = portfolio_value * current_yield / 12

        year = (month - 1) // 12 + 1
        mo = (month - 1) % 12 + 1

        if month % 6 == 0 or month == 1 or monthly_income_after >= goal_monthly_income:
            snapshots.append({
                "month": month,
                "year": year,
                "month_of_year": mo,
                "portfolio_value": round(portfolio_value, 2),
                "monthly_income": round(monthly_income_after, 2),
                "annual_income": round(monthly_income_after * 12, 2),
                "total_contributed": round(starting_capital + monthly_contribution * month, 2),
                "growth": round(portfolio_value - (starting_capital + monthly_contribution * month), 2),
                "yield_on_cost": round(current_yield * 100, 3),
            })

        if monthly_income_after >= goal_monthly_income and reached_goal_at is None:
            reached_goal_at = {"month": month, "year": year, "month_label": f"Month {month}"}

    return snapshots, reached_goal_at


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


def _cache_read() -> dict | None:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("cached_at", 0) > _CACHE_TTL:
            return None
        return data
    except Exception:
        return None


def _cache_write(data: dict) -> None:
    try:
        data["cached_at"] = time.time()
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("dividend_path cache write failed: %s", e)


def build_dividend_path(
    starting_capital: float = 61000.0,
    weekly_dca: float = 500.0,
    force: bool = False,
) -> dict:
    """
    Main entry point: scan universe, select portfolio, project income path.
    Results cached for 6 hours.
    """
    if not force:
        cached = _cache_read()
        if cached:
            logger.info("dividend_path: returning cached results")
            return cached

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
        raise RuntimeError("No dividend data available — check API keys")

    scored_all.sort(key=lambda x: x["score"], reverse=True)
    portfolio = _select_portfolio(scored_all)

    snapshots, reached_goal_at = _build_projection(portfolio, starting_capital, weekly_dca)

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
        "reached_goal_at": reached_goal_at,
        "projection": snapshots,
        "top_candidates": scored_all[:15],
    }
    _cache_write(output)
    logger.info("dividend_path complete: %d scored, portfolio of %d", len(scored_all), len(portfolio))
    return output
