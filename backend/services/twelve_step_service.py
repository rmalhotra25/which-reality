"""
Data aggregation for the 12-Step stock analysis framework.
Merges Finnhub TTM metrics with Polygon multi-year annual financials.
"""
import concurrent.futures
import logging

from services.finnhub_client import get_basic_financials, get_company_profile
from services.polygon_client import get_ticker_snapshot

logger = logging.getLogger(__name__)


def _get_annual_financials_list(ticker: str, years: int = 5) -> list[dict]:
    """Annual financials for the last N fiscal years, most recent first."""
    from services.polygon_client import _client
    c = _client()

    def _v(obj, *attrs):
        for a in attrs:
            v = getattr(obj, a, None)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    result = []
    try:
        items = list(c.list_financials(
            ticker=ticker, timeframe="annual", limit=years, order="desc", include_sources=False
        ))
        for fin in items:
            fins = getattr(fin, "financials", None)
            if not fins:
                continue
            period = (
                getattr(fin, "fiscal_year", None)
                or str(getattr(fin, "end_date", "") or "")[:4]
                or ""
            )
            row: dict = {"period": str(period)}
            inc = getattr(fins, "income_statement", None)
            if inc:
                row["revenue"] = _v(inc, "revenues", "revenue")
                row["gross_profit"] = _v(inc, "gross_profit")
                row["operating_income"] = _v(inc, "operating_income_loss")
                row["net_income"] = _v(inc, "net_income_loss")
                row["shares"] = _v(inc, "diluted_average_shares", "basic_average_shares")
                row["cost_of_revenue"] = _v(inc, "cost_of_revenue")
                row["operating_expenses"] = _v(inc, "operating_expenses")
            bs = getattr(fins, "balance_sheet", None)
            if bs:
                row["total_debt"] = _v(
                    bs, "long_term_debt", "debt_and_capital_lease_obligations"
                )
                row["cash"] = _v(
                    bs,
                    "cash_and_cash_equivalents_including_restricted_cash",
                    "cash_and_cash_equivalents",
                )
            cf = getattr(fins, "cash_flow_statement", None)
            if cf:
                ocf = _v(cf, "net_cash_flow_from_operating_activities")
                capex = _v(cf, "capital_expenditure")
                row["operating_cash_flow"] = ocf
                row["capex"] = capex
                if ocf is not None and capex is not None:
                    row["free_cash_flow"] = ocf + capex  # capex stored as negative
            result.append(row)
    except Exception as e:
        logger.warning("_get_annual_financials_list failed for %s: %s", ticker, e)
    return result


def get_twelve_step_data(ticker: str) -> dict:
    """Return all financial data needed for the 12-step wizard."""
    ticker = ticker.upper().strip()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        f_basics = pool.submit(get_basic_financials, ticker)
        f_profile = pool.submit(get_company_profile, ticker)
        f_snap = pool.submit(get_ticker_snapshot, ticker)
        f_annual = pool.submit(_get_annual_financials_list, ticker, 5)

    basics: dict = f_basics.result() or {}
    profile: dict = f_profile.result() or {}
    snapshot: dict = f_snap.result() or {}
    annual: list = f_annual.result()

    def _m(*keys):
        for k in keys:
            v = basics.get(k)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    current_price = snapshot.get("price") or _m("52WeekLow") or None
    market_cap_millions = _m("marketCapitalization") or profile.get("marketCapitalization")

    return {
        "ticker": ticker,
        "company_name": profile.get("name") or ticker,
        "sector": (
            profile.get("finnhubIndustry")
            or profile.get("gics_sector")
            or ""
        ),
        "current_price": current_price,
        "market_cap": float(market_cap_millions) * 1e6 if market_cap_millions else None,
        "shares_outstanding": _m("sharesOutstanding"),
        "ttm": {
            "pe": _m("peNormalizedAnnual", "peBasicExclExtraTTM", "peExclExtraTTM"),
            "gross_margin": _m("grossMarginTTM", "grossMarginAnnual"),
            "operating_margin": _m("operatingMarginTTM", "operatingMarginAnnual"),
            "net_margin": _m("netProfitMarginTTM", "netProfitMarginAnnual"),
            "fcf_margin": _m("fcfMarginTTM", "freeCashFlowMargin5Y"),
            "revenue_growth_yoy": _m("revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy"),
            "revenue_growth_5y": _m("revenueGrowth5Y"),
            "eps_growth_5y": _m("epsGrowth5Y"),
            "eps": _m("epsBasicExclExtraAnnual", "epsNormalizedAnnual"),
            "free_cash_flow": _m("freeCashFlowTTM", "freeCashFlowAnnual"),
            "revenue": _m("revenuePerShareTTM"),
            "roic": _m("roicTTM"),
        },
        "annual": annual,
    }
