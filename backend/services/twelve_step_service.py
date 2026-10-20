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

    def _f(obj, *attrs):
        for a in attrs:
            v = getattr(obj, a, None)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    try:
        kw = dict(tickers=ticker, timeframe="annual", limit=years, sort="desc")
        inc_rows = list(c.list_financials_income_statements(**kw))
        bs_rows  = list(c.list_financials_balance_sheets(**kw))
        cf_rows  = list(c.list_financials_cash_flow_statements(**kw))

        def _year(r):
            return str(int(r.fiscal_year)) if r.fiscal_year else str(r.period_end or "")[:4]

        bs_by_year = {_year(r): r for r in bs_rows}
        cf_by_year = {_year(r): r for r in cf_rows}

        result = []
        for inc in inc_rows:
            period = _year(inc)
            bs = bs_by_year.get(period)
            cf = cf_by_year.get(period)
            row: dict = {"period": period}

            row["revenue"]           = _f(inc, "revenue")
            row["gross_profit"]      = _f(inc, "gross_profit")
            row["operating_income"]  = _f(inc, "operating_income")
            row["net_income"]        = _f(inc, "net_income_loss_attributable_common_shareholders",
                                          "consolidated_net_income_loss")
            row["shares"]            = _f(inc, "diluted_shares_outstanding", "basic_shares_outstanding")
            row["cost_of_revenue"]   = _f(inc, "cost_of_revenue")
            row["operating_expenses"] = _f(inc, "total_operating_expenses")

            if bs:
                row["total_debt"] = _f(bs, "long_term_debt_and_capital_lease_obligations")
                row["cash"]       = _f(bs, "cash_and_equivalents")

            if cf:
                ocf   = _f(cf, "net_cash_from_operating_activities")
                capex = _f(cf, "purchase_of_property_plant_and_equipment")
                row["operating_cash_flow"] = ocf
                row["capex"] = capex
                if ocf is not None and capex is not None:
                    row["free_cash_flow"] = ocf + capex  # capex is negative (cash outflow)

            result.append(row)
        return result
    except Exception as e:
        logger.warning("_get_annual_financials_list failed for %s: %s", ticker, e)
        return []


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
