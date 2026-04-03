import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    logger.warning("yfinance not available — using Yahoo Finance JSON API fallback")

# Curated universe of liquid, optionable stocks/ETFs used as candidates
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC",
    "JPM", "BAC", "GS", "MS", "WFC",
    "SPY", "QQQ", "IWM", "GLD", "SLV", "TLT",
    "XOM", "CVX", "COP",
    "JNJ", "PFE", "UNH", "ABBV",
    "COST", "WMT", "TGT", "HD",
    "DIS", "NFLX", "CMCSA",
    "V", "MA", "PYPL",
    "BA", "CAT", "DE",
    "KO", "PEP", "MCD",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _yf_fetch_quote(ticker: str) -> dict:
    """Fetch quote via Yahoo Finance JSON API (no yfinance required)."""
    import requests
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {}
        meta = result[0].get("meta", {})
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        return {
            "price": meta.get("regularMarketPrice"),
            "prev_close": meta.get("chartPreviousClose"),
            "closes": closes,
            "volume": meta.get("regularMarketVolume"),
        }
    except Exception as e:
        logger.debug("YF chart API error for %s: %s", ticker, e)
        return {}


def _yf_fetch_summary(ticker: str) -> dict:
    """Fetch fundamentals via Yahoo Finance quoteSummary API."""
    import requests
    try:
        url = (
            f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
            "?modules=summaryDetail,financialData,defaultKeyStatistics"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json().get("quoteSummary", {}).get("result", [{}])[0]
        sd = data.get("summaryDetail", {})
        fd = data.get("financialData", {})
        ks = data.get("defaultKeyStatistics", {})
        return {
            "pe_ratio": sd.get("trailingPE", {}).get("raw"),
            "eps_growth_ttm": fd.get("earningsGrowth", {}).get("raw"),
            "revenue_growth_ttm": fd.get("revenueGrowth", {}).get("raw"),
            "div_yield": sd.get("dividendYield", {}).get("raw"),
            "sector": "",
            "analyst_rating": fd.get("recommendationKey", "none"),
            "52w_high": sd.get("fiftyTwoWeekHigh", {}).get("raw"),
            "52w_low": sd.get("fiftyTwoWeekLow", {}).get("raw"),
        }
    except Exception as e:
        logger.debug("YF summary API error for %s: %s", ticker, e)
        return {}


class StockDataService:
    def get_price_data(self, tickers: list[str]) -> dict:
        result = {}
        for ticker in tickers:
            try:
                if _YF_AVAILABLE:
                    t = yf.Ticker(ticker)
                    hist = t.history(period="10d")
                    if hist.empty:
                        continue
                    current_price = float(hist["Close"].iloc[-1])
                    price_5d_ago = float(hist["Close"].iloc[max(0, len(hist) - 6)])
                    change_5d_pct = ((current_price - price_5d_ago) / price_5d_ago) * 100
                    result[ticker] = {
                        "price": round(current_price, 2),
                        "change_5d_pct": round(change_5d_pct, 2),
                        "volume": int(hist["Volume"].iloc[-1]),
                        "market_cap": None,
                    }
                else:
                    q = _yf_fetch_quote(ticker)
                    if not q or not q.get("price"):
                        continue
                    closes = q.get("closes", [])
                    price = float(q["price"])
                    price_5d_ago = float(closes[-6]) if len(closes) >= 6 else price
                    change_5d_pct = ((price - price_5d_ago) / price_5d_ago) * 100 if price_5d_ago else 0
                    result[ticker] = {
                        "price": round(price, 2),
                        "change_5d_pct": round(change_5d_pct, 2),
                        "volume": q.get("volume") or 0,
                        "market_cap": None,
                    }
            except Exception as e:
                logger.debug("Price data error for %s: %s", ticker, e)
        return result

    def get_options_data(self, tickers: list[str]) -> dict:
        if not _YF_AVAILABLE:
            return {}  # Options chain requires yfinance; return empty, Claude will work without it
        result = {}
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                expiries = t.options
                if not expiries:
                    continue
                chain = t.option_chain(expiries[0])
                calls = chain.calls
                info = t.fast_info
                current_price = getattr(info, "last_price", None)
                if not current_price or calls.empty:
                    continue
                atm_calls = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:1]]
                atm_iv = float(atm_calls["impliedVolatility"].iloc[0]) * 100 if not atm_calls.empty else None
                result[ticker] = {
                    "nearest_expiry": expiries[0],
                    "atm_iv": round(atm_iv, 1) if atm_iv else None,
                    "iv_rank_approx": min(100, round(atm_iv / 0.5, 1)) if atm_iv else None,
                }
            except Exception as e:
                logger.debug("Options data error for %s: %s", ticker, e)
        return result

    def get_fundamentals(self, tickers: list[str]) -> dict:
        result = {}
        for ticker in tickers:
            try:
                if _YF_AVAILABLE:
                    t = yf.Ticker(ticker)
                    info = t.info
                    result[ticker] = {
                        "pe_ratio": info.get("trailingPE"),
                        "eps_growth_ttm": info.get("earningsGrowth"),
                        "revenue_growth_ttm": info.get("revenueGrowth"),
                        "div_yield": info.get("dividendYield"),
                        "sector": info.get("sector", "Unknown"),
                        "analyst_rating": info.get("recommendationKey", "none"),
                    }
                else:
                    fund = _yf_fetch_summary(ticker)
                    if fund:
                        result[ticker] = fund
            except Exception as e:
                logger.debug("Fundamentals error for %s: %s", ticker, e)
        return result

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            if _YF_AVAILABLE:
                return float(yf.Ticker(ticker).fast_info.last_price)
            else:
                q = _yf_fetch_quote(ticker)
                return float(q["price"]) if q.get("price") else None
        except Exception:
            return None

    def get_wheel_screening_data(self, tickers: list[str]) -> dict:
        prices = self.get_price_data(tickers)
        options = self.get_options_data(tickers)
        result = {}
        for ticker in tickers:
            if ticker in prices:
                result[ticker] = {**prices[ticker], **(options.get(ticker, {}))}
        return result
