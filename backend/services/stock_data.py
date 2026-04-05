import logging
import json
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    logger.warning("yfinance not available — using Yahoo Finance JSON API fallback")

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


# ---------------------------------------------------------------------------
# Technical indicator calculations (pure numpy/pandas, no extra libraries)
# ---------------------------------------------------------------------------

def _rsi(closes: pd.Series, period: int = 14) -> float:
    """Relative Strength Index."""
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1) if not rsi.empty else None


def _macd(closes: pd.Series) -> dict:
    """MACD line, signal line, and histogram."""
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    return {
        "macd": round(float(macd_line.iloc[-1]), 3),
        "signal": round(float(signal.iloc[-1]), 3),
        "histogram": round(float(histogram.iloc[-1]), 3),
        "crossover": (
            "bullish" if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0
            else "bearish" if histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0
            else "neutral"
        ),
    }


def _bollinger_bands(closes: pd.Series, period: int = 20) -> dict:
    """Bollinger Bands: upper, middle (SMA), lower, and %B."""
    sma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    price = closes.iloc[-1]
    pct_b = (price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) if upper.iloc[-1] != lower.iloc[-1] else 0.5
    return {
        "upper": round(float(upper.iloc[-1]), 2),
        "middle": round(float(sma.iloc[-1]), 2),
        "lower": round(float(lower.iloc[-1]), 2),
        "pct_b": round(float(pct_b), 2),        # 0=at lower, 1=at upper, 0.5=at middle
        "squeeze": bool(((upper - lower) / sma).iloc[-1] < 0.10),  # tight bands = squeeze
    }


def _moving_averages(closes: pd.Series) -> dict:
    """20, 50, and 200-day simple moving averages + trend signals."""
    price = closes.iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1] if len(closes) >= 20 else None
    ma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
    ma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else None
    return {
        "ma20": round(float(ma20), 2) if ma20 else None,
        "ma50": round(float(ma50), 2) if ma50 else None,
        "ma200": round(float(ma200), 2) if ma200 else None,
        "above_ma20": bool(price > ma20) if ma20 else None,
        "above_ma50": bool(price > ma50) if ma50 else None,
        "above_ma200": bool(price > ma200) if ma200 else None,
        "golden_cross": bool(ma50 > ma200) if (ma50 and ma200) else None,   # bullish
        "death_cross": bool(ma50 < ma200) if (ma50 and ma200) else None,    # bearish
    }


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Average True Range — measures daily volatility in dollar terms."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 2) if not np.isnan(atr) else None


def _vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> float:
    """Volume-Weighted Average Price over the available window."""
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    return round(float(vwap.iloc[-1]), 2)


def _fibonacci_levels(closes: pd.Series, window: int = 50) -> dict:
    """Key Fibonacci retracement levels based on recent high/low."""
    recent = closes.tail(window)
    high = float(recent.max())
    low = float(recent.min())
    diff = high - low
    return {
        "high": round(high, 2),
        "low": round(low, 2),
        "fib_236": round(high - 0.236 * diff, 2),
        "fib_382": round(high - 0.382 * diff, 2),
        "fib_500": round(high - 0.500 * diff, 2),
        "fib_618": round(high - 0.618 * diff, 2),
        "fib_786": round(high - 0.786 * diff, 2),
    }


def _support_resistance(closes: pd.Series, window: int = 50) -> dict:
    """Simple pivot-point based support and resistance levels."""
    recent = closes.tail(window)
    pivot = float(recent.mean())
    std = float(recent.std())
    return {
        "resistance_1": round(pivot + std, 2),
        "resistance_2": round(pivot + 2 * std, 2),
        "support_1": round(pivot - std, 2),
        "support_2": round(pivot - 2 * std, 2),
        "pivot": round(pivot, 2),
    }


def _volume_trend(volumes: pd.Series) -> dict:
    """Compare recent 5-day avg volume to 20-day avg volume."""
    vol_5 = float(volumes.tail(5).mean())
    vol_20 = float(volumes.tail(20).mean())
    ratio = vol_5 / vol_20 if vol_20 else 1.0
    return {
        "avg_vol_5d": int(vol_5),
        "avg_vol_20d": int(vol_20),
        "ratio": round(ratio, 2),
        "trend": "high" if ratio > 1.5 else "low" if ratio < 0.7 else "normal",
    }


def _compute_all_indicators(df: pd.DataFrame) -> dict:
    """Given a DataFrame with Open/High/Low/Close/Volume, compute all indicators."""
    closes = df["Close"].dropna()
    if len(closes) < 26:
        return {}   # not enough history

    indicators = {}
    try:
        indicators["rsi"] = _rsi(closes)
    except Exception:
        pass
    try:
        indicators["macd"] = _macd(closes)
    except Exception:
        pass
    try:
        indicators["bollinger"] = _bollinger_bands(closes)
    except Exception:
        pass
    try:
        indicators["moving_averages"] = _moving_averages(closes)
    except Exception:
        pass
    try:
        indicators["atr"] = _atr(df["High"], df["Low"], df["Close"])
    except Exception:
        pass
    try:
        indicators["vwap"] = _vwap(df["High"], df["Low"], df["Close"], df["Volume"])
    except Exception:
        pass
    try:
        indicators["fibonacci"] = _fibonacci_levels(closes)
    except Exception:
        pass
    try:
        indicators["support_resistance"] = _support_resistance(closes)
    except Exception:
        pass
    try:
        indicators["volume_trend"] = _volume_trend(df["Volume"])
    except Exception:
        pass
    return indicators


# ---------------------------------------------------------------------------
# Yahoo Finance HTTP fallback (no yfinance)
# ---------------------------------------------------------------------------

def _yf_fetch_ohlcv(ticker: str, period_days: int = 200) -> pd.DataFrame:
    """Fetch OHLCV history via Yahoo Finance chart API."""
    import requests
    try:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&range={period_days}d"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        result = r.json().get("chart", {}).get("result", [])
        if not result:
            return pd.DataFrame()
        timestamps = result[0].get("timestamp", [])
        q = result[0].get("indicators", {}).get("quote", [{}])[0]
        df = pd.DataFrame({
            "Date": pd.to_datetime(timestamps, unit="s"),
            "Open":   q.get("open", []),
            "High":   q.get("high", []),
            "Low":    q.get("low", []),
            "Close":  q.get("close", []),
            "Volume": q.get("volume", []),
        }).dropna(subset=["Close"])
        df.set_index("Date", inplace=True)
        return df
    except Exception as e:
        logger.debug("OHLCV fetch error for %s: %s", ticker, e)
        return pd.DataFrame()


def _yf_fetch_summary(ticker: str) -> dict:
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
        logger.debug("YF summary error for %s: %s", ticker, e)
        return {}


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------

class StockDataService:

    def _get_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Return OHLCV DataFrame regardless of whether yfinance is available."""
        if _YF_AVAILABLE:
            try:
                df = yf.Ticker(ticker).history(period=period)
                if not df.empty:
                    return df
            except Exception:
                pass
        # Fallback: determine day count from period string
        days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 252, "2y": 504}.get(period, 252)
        return _yf_fetch_ohlcv(ticker, period_days=days)

    def get_price_and_technicals(self, ticker: str) -> dict:
        """
        Returns current price + full technical indicator suite for one ticker.
        This is the main method used by all three analysis engines.
        """
        df = self._get_history(ticker, period="1y")
        if df.empty or len(df) < 26:
            return {}

        closes = df["Close"].dropna()
        price = float(closes.iloc[-1])
        price_5d_ago = float(closes.iloc[max(0, len(closes) - 6)])
        change_5d_pct = round(((price - price_5d_ago) / price_5d_ago) * 100, 2)

        result = {
            "price": round(price, 2),
            "change_5d_pct": change_5d_pct,
            "volume": int(df["Volume"].iloc[-1]),
        }
        result.update(_compute_all_indicators(df))
        return result

    def get_price_data(self, tickers: list[str]) -> dict:
        """Lightweight price-only data (used when full technicals not needed)."""
        result = {}
        for ticker in tickers:
            try:
                d = self.get_price_and_technicals(ticker)
                if d:
                    result[ticker] = {k: d[k] for k in ("price", "change_5d_pct", "volume") if k in d}
            except Exception as e:
                logger.debug("Price data error for %s: %s", ticker, e)
        return result

    def get_technicals_bulk(self, tickers: list[str]) -> dict:
        """Full price + technicals for a list of tickers."""
        result = {}
        for ticker in tickers:
            try:
                d = self.get_price_and_technicals(ticker)
                if d:
                    result[ticker] = d
            except Exception as e:
                logger.debug("Technicals error for %s: %s", ticker, e)
        return result

    def get_options_data(self, tickers: list[str]) -> dict:
        if not _YF_AVAILABLE:
            return {}
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
                atm = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:1]]
                atm_iv = float(atm["impliedVolatility"].iloc[0]) * 100 if not atm.empty else None
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
                    info = yf.Ticker(ticker).info
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
            df = _yf_fetch_ohlcv(ticker, period_days=5)
            return float(df["Close"].iloc[-1]) if not df.empty else None
        except Exception:
            return None

    def get_wheel_screening_data(self, tickers: list[str]) -> dict:
        """Full technicals + options IV for wheel strategy screening."""
        technicals = self.get_technicals_bulk(tickers)
        options = self.get_options_data(tickers)
        for ticker in technicals:
            if ticker in options:
                technicals[ticker].update(options[ticker])
        return technicals
