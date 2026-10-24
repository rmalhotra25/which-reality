"""
Data aggregation for the 12-Step stock analysis framework.
Merges Finnhub TTM metrics with Polygon multi-year annual financials.
"""
import concurrent.futures
import logging

from services.finnhub_client import get_basic_financials, get_company_profile
from services.polygon_client import get_ticker_snapshot  # price/market-cap snapshot

logger = logging.getLogger(__name__)


def _get_annual_financials_list(ticker: str, years: int = 5) -> list[dict]:
    """Annual financials for the last N fiscal years via yfinance (most recent first)."""
    try:
        import math
        import yfinance as yf

        stock = yf.Ticker(ticker)
        income  = stock.income_stmt    # columns = fiscal year-end dates, descending
        balance = stock.balance_sheet
        cashflow = stock.cashflow

        if income is None or income.empty:
            logger.warning("yfinance: no income data for %s", ticker)
            return []

        def _v(df, col, *names):
            if df is None or df.empty or col not in df.columns:
                return None
            for name in names:
                if name in df.index:
                    try:
                        fv = float(df.at[name, col])
                        if not math.isnan(fv):
                            return fv
                    except Exception:
                        pass
            return None

        result = []
        for col in list(income.columns)[:years]:
            year = str(col.year) if hasattr(col, "year") else str(col)[:4]

            ocf   = _v(cashflow, col, "Operating Cash Flow")
            capex = _v(cashflow, col, "Capital Expenditure")
            fcf   = _v(cashflow, col, "Free Cash Flow")
            if fcf is None and ocf is not None and capex is not None:
                fcf = ocf + capex  # capex is negative in yfinance

            result.append({
                "period":            year,
                "revenue":           _v(income, col, "Total Revenue"),
                "gross_profit":      _v(income, col, "Gross Profit"),
                "operating_income":  _v(income, col, "Operating Income",
                                        "Total Operating Income As Reported"),
                "net_income":        _v(income, col, "Net Income",
                                        "Net Income Common Stockholders"),
                "shares":            _v(income, col, "Diluted Average Shares", "Diluted Shares",
                                        "Basic Average Shares", "Basic Shares"),
                "cost_of_revenue":   _v(income, col, "Cost Of Revenue"),
                "operating_expenses": _v(income, col, "Total Operating Expenses",
                                         "Operating Expense"),
                "total_debt":        _v(balance, col, "Total Debt", "Long Term Debt"),
                "cash":              _v(balance, col, "Cash And Cash Equivalents",
                                        "Cash Cash Equivalents And Short Term Investments"),
                "operating_cash_flow": ocf,
                "capex":             capex,
                "free_cash_flow":    fcf,
            })
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

    # No price fallback: if the live snapshot has no price, report None and let
    # the wizard block the DCF and verdict as "price unavailable". The 52-week
    # low must never stand in as the current price.
    current_price = snapshot.get("price") or None
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
