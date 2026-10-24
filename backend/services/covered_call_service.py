"""
Deterministic covered-call checks (review items M6, M39, M43).

This service holds the math the old analyzer left to prompt text and flags:
income capture, the 0.3%-per-week minimum premium, and the earnings and
ex-dividend calendar check. Everything here is a pure function of its inputs:
no language-model estimates, no mid price presented as collectible cash.

CEF distributions: this service counts each distribution exactly once. The
premium math in compute_covered_call_impact takes premium only. A CEF
distribution, when the caller passes it, is reported on its own line
(distribution_return_pct, distribution_dollars) and is added to the total
return once, never folded into income capture. No distribution figure is
added anywhere else in this file.

Note on the review citation: backend/services/covered_call_service.py did not
exist at origin/master ec943f4, and no _compute_covered_call_impact or
income_capture_pct exists anywhere in the repo at that commit (searched all
of backend/ and frontend/src/). The covered-call analyzer at that commit is
stock_data.get_call_tiers (tiers plus a below_threshold flag) plus
claude_analyst.suggest_covered_calls (prompt text). This file is new: it
supplies the deterministic functions the review describes so a router can
wire them in without touching the prompt-driven path.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

MIN_WEEKLY_PREMIUM_PCT = 0.003  # 0.3% of the stock price per week


def compute_covered_call_impact(
    price_at_sale: float,
    price_at_expiry: float,
    premium_sold_per_share: float,
    premium_captured_per_share: float,
    shares: int = 100,
    distributions_per_share: float = 0.0,
) -> dict:
    """Income and return of one covered call, with each part kept separate.

    income_capture_pct is premium captured divided by premium sold: the share
    of the premium actually kept. A falling stock does not change it, because
    the stock move is reported on its own line (stock_return_pct) and never
    added to income. Distributions (for example a CEF monthly payout) are
    reported separately and added to the total exactly once.
    """
    price_at_sale = float(price_at_sale)
    price_at_expiry = float(price_at_expiry)
    premium_sold = float(premium_sold_per_share)
    premium_captured = float(premium_captured_per_share)
    distributions = float(distributions_per_share)
    shares = int(shares)

    if premium_sold > 0:
        income_capture_pct = round(premium_captured / premium_sold * 100, 2)
    else:
        income_capture_pct = 0.0

    stock_return_pct = round((price_at_expiry - price_at_sale) / price_at_sale * 100, 2) if price_at_sale > 0 else 0.0
    premium_return_pct = round(premium_captured / price_at_sale * 100, 2) if price_at_sale > 0 else 0.0
    distribution_return_pct = round(distributions / price_at_sale * 100, 2) if price_at_sale > 0 else 0.0
    total_return_pct = round(stock_return_pct + premium_return_pct + distribution_return_pct, 2)

    stock_dollars = round((price_at_expiry - price_at_sale) * shares, 2)
    premium_dollars = round(premium_captured * shares, 2)
    distribution_dollars = round(distributions * shares, 2)
    total_dollars = round(stock_dollars + premium_dollars + distribution_dollars, 2)

    return {
        "income_capture_pct": income_capture_pct,
        "premium_sold_per_share": round(premium_sold, 4),
        "premium_captured_per_share": round(premium_captured, 4),
        "premium_dollars": premium_dollars,
        "stock_return_pct": stock_return_pct,
        "stock_dollars": stock_dollars,
        "premium_return_pct": premium_return_pct,
        "distribution_return_pct": distribution_return_pct,
        "distribution_dollars": distribution_dollars,
        "total_return_pct": total_return_pct,
        "total_dollars": total_dollars,
    }


def evaluate_premium_threshold(
    bid: float | None,
    ask: float | None,
    price: float,
    dte: int,
    min_weekly_pct: float = MIN_WEEKLY_PREMIUM_PCT,
) -> dict:
    """Hard 0.3%-per-week minimum premium test, net of spread, at the bid.

    A seller collects the bid, never the mid, so the test uses the bid. The
    spread is the cost of exiting, so the net premium is bid minus spread
    (ask minus bid). When there is no live bid/ask (both 0.0 on this data
    plan), the threshold cannot be verified at the bid and the tier abstains
    instead of passing on a mid or last-trade price.
    """
    price = float(price)
    weeks = max(int(dte), 1) / 7.0
    required = round(price * min_weekly_pct * weeks, 4)

    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return {
            "passes": False,
            "abstain": True,
            "net_premium_per_share": None,
            "required_premium_per_share": required,
            "spread_per_share": None,
            "spread_unknown": True,
            "reason": "No live bid/ask: the 0.3%-per-week threshold cannot be verified at the bid, so abstain.",
        }

    spread = round(float(ask) - float(bid), 4)
    net = round(float(bid) - spread, 4)
    passes = net >= required
    return {
        "passes": passes,
        "abstain": not passes,
        "net_premium_per_share": net,
        "required_premium_per_share": required,
        "spread_per_share": spread,
        "spread_unknown": False,
        "reason": (
            "Net premium at the bid clears the 0.3%-per-week minimum."
            if passes
            else "Net premium at the bid is below the 0.3%-per-week minimum, so abstain."
        ),
    }


def check_earnings_exdiv(
    expiry: date,
    earnings_date: date | None = None,
    next_ex_div_date: date | None = None,
    current_price: float | None = None,
    strike: float | None = None,
) -> dict:
    """Deterministic earnings and ex-dividend check before recommending a call.

    Earnings on or before expiry blocks the recommendation (gap and IV-crush
    risk). An ex-dividend date on or before expiry blocks it when the call is
    in the money (early-assignment risk) and warns otherwise (the dividend
    goes to the buyer if the shares are called away). Unknown dates warn
    instead of blocking.
    """
    blocked = False
    reasons: list[str] = []
    warnings: list[str] = []

    if earnings_date is not None:
        if earnings_date <= expiry:
            blocked = True
            reasons.append(
                f"Earnings on {earnings_date.isoformat()} fall before expiry "
                f"{expiry.isoformat()}: suppress the call."
            )
    else:
        warnings.append("No earnings date available: check the calendar before selling.")

    if next_ex_div_date is not None:
        if next_ex_div_date <= expiry:
            is_itm = (
                current_price is not None
                and strike is not None
                and current_price > strike
            )
            if is_itm:
                blocked = True
                reasons.append(
                    f"Ex-dividend date {next_ex_div_date.isoformat()} falls before "
                    f"expiry {expiry.isoformat()} and the call is in the money: "
                    "early-assignment risk, suppress the call."
                )
            else:
                warnings.append(
                    f"Ex-dividend date {next_ex_div_date.isoformat()} falls before "
                    f"expiry {expiry.isoformat()}: the dividend goes to the buyer "
                    "if the shares are called away."
                )
    else:
        warnings.append("No ex-dividend date available: check the calendar before selling.")

    return {
        "blocked": blocked,
        "reasons": reasons,
        "warnings": warnings,
    }


def get_earnings_and_exdiv_dates(ticker: str) -> dict:
    """Best-effort fetch of the next earnings date and next ex-dividend date.

    Earnings come from the Finnhub calendar (days until next earnings);
    the ex-dividend date comes from Polygon dividends. Any failure returns
    None for that date instead of raising, so the caller warns on unknown
    rather than crashing the analyzer.
    """
    ticker = ticker.upper().strip()
    today = date.today()
    earnings_date = None
    next_ex_div_date = None

    try:
        from services.finnhub_client import get_earnings_this_month
        days = get_earnings_this_month(ticker)
        if days is not None:
            earnings_date = today + timedelta(days=int(days))
    except Exception as e:
        logger.debug("covered-call earnings fetch failed for %s: %s", ticker, e)

    try:
        from services.polygon_client import _client
        items = list(_client().list_dividends(
            ticker=ticker,
            ex_dividend_date_gte=today.isoformat(),
            limit=5,
            order="asc",
        ))
        for item in items or []:
            raw = str(getattr(item, "ex_dividend_date", "") or "")
            try:
                parsed = date.fromisoformat(raw) if raw else None
            except ValueError:
                parsed = None
            if parsed is not None and parsed >= today:
                next_ex_div_date = parsed
                break
    except Exception as e:
        logger.debug("covered-call ex-div fetch failed for %s: %s", ticker, e)

    return {
        "earnings_date": earnings_date,
        "next_ex_div_date": next_ex_div_date,
    }


def evaluate_tier(
    tier: dict | None,
    current_price: float,
    earnings_date: date | None = None,
    next_ex_div_date: date | None = None,
) -> dict:
    """Run the threshold and calendar checks for one call tier.

    Returns the tier with abstain True when the premium test fails or the
    calendar blocks it. A tier with no contract (None) abstains as well.
    """
    if not tier:
        return {
            "tier": None,
            "abstain": True,
            "abstain_reasons": ["No suitable option found for this tier."],
            "warnings": [],
            "threshold": None,
            "calendar": None,
        }

    expiry_raw = tier.get("expiry")
    try:
        expiry = date.fromisoformat(str(expiry_raw)) if expiry_raw else None
    except ValueError:
        expiry = None

    threshold = evaluate_premium_threshold(
        tier.get("bid"), tier.get("ask"), current_price, tier.get("dte", 7)
    )
    calendar = None
    if expiry is not None:
        calendar = check_earnings_exdiv(
            expiry,
            earnings_date=earnings_date,
            next_ex_div_date=next_ex_div_date,
            current_price=current_price,
            strike=tier.get("strike"),
        )

    abstain_reasons: list[str] = []
    warnings: list[str] = []
    if not threshold["passes"]:
        abstain_reasons.append(threshold["reason"])
    if calendar is not None:
        if calendar["blocked"]:
            abstain_reasons.extend(calendar["reasons"])
        warnings.extend(calendar["warnings"])

    return {
        "tier": tier,
        "abstain": bool(abstain_reasons),
        "abstain_reasons": abstain_reasons,
        "warnings": warnings,
        "threshold": threshold,
        "calendar": calendar,
    }
