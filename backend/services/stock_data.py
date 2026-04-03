import logging
from typing import Optional
import yfinance as yf

logger = logging.getLogger(__name__)

# Curated universe of liquid, optionable stocks/ETFs used as candidates
# when we don't have specific tickers from news yet
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


class StockDataService:
    def get_price_data(self, tickers: list[str]) -> dict:
        """Returns dict of ticker → {price, change_5d_pct, rsi, volume, market_cap}."""
        result = {}
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
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
                    "market_cap": getattr(info, "market_cap", None),
                }
            except Exception as e:
                logger.debug("Price data error for %s: %s", ticker, e)
        return result

    def get_options_data(self, tickers: list[str]) -> dict:
        """Returns dict of ticker → {iv_rank_approx, nearest_expiry, atm_iv}."""
        result = {}
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                expiries = t.options
                if not expiries:
                    continue
                nearest = expiries[0]
                chain = t.option_chain(nearest)
                calls = chain.calls
                puts = chain.puts
                if calls.empty:
                    continue
                info = t.fast_info
                current_price = getattr(info, "last_price", None)
                if not current_price:
                    continue
                # Approximate ATM IV using nearest strike
                atm_calls = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:1]]
                atm_iv = float(atm_calls["impliedVolatility"].iloc[0]) * 100 if not atm_calls.empty else None
                result[ticker] = {
                    "nearest_expiry": nearest,
                    "atm_iv": round(atm_iv, 1) if atm_iv else None,
                    "iv_rank_approx": min(100, round(atm_iv / 0.5, 1)) if atm_iv else None,
                }
            except Exception as e:
                logger.debug("Options data error for %s: %s", ticker, e)
        return result

    def get_fundamentals(self, tickers: list[str]) -> dict:
        """Returns dict of ticker → {pe_ratio, eps_growth, rev_growth, div_yield, sector}."""
        result = {}
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.info
                result[ticker] = {
                    "pe_ratio": info.get("trailingPE"),
                    "eps_growth_ttm": info.get("earningsGrowth"),
                    "revenue_growth_ttm": info.get("revenueGrowth"),
                    "div_yield": info.get("dividendYield"),
                    "sector": info.get("sector", "Unknown"),
                    "analyst_rating": info.get("recommendationKey", "none"),
                    "52w_high": info.get("fiftyTwoWeekHigh"),
                    "52w_low": info.get("fiftyTwoWeekLow"),
                }
            except Exception as e:
                logger.debug("Fundamentals error for %s: %s", ticker, e)
        return result

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            return float(info.last_price)
        except Exception:
            return None

    def get_wheel_screening_data(self, tickers: list[str]) -> dict:
        """Combined price + options for wheel screening."""
        prices = self.get_price_data(tickers)
        options = self.get_options_data(tickers)
        result = {}
        for ticker in tickers:
            if ticker in prices:
                entry = {**prices[ticker]}
                if ticker in options:
                    entry.update(options[ticker])
                result[ticker] = entry
        return result
