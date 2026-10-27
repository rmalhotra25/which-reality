import logging
import json
import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _sale_price_for_row(row: dict) -> tuple[float, float, str]:
    """
    Sale price for a wheel option from a normalized chain row.

    Returns (sale_price, mid, premium_source). The sale price is the
    bid, what the seller actually collects. Rows built by
    ChainProvider already carry sale_price / price_source; rows built
    elsewhere (synthetic Black-Scholes tiers, older fixtures) are
    resolved from bid/ask here, so no path can price a sale at a last
    trade. A last trade is never an executable sale price.
    """
    if row.get("sale_price") is not None and row.get("price_source"):
        return (
            round(float(row.get("sale_price") or 0), 2),
            round(float(row.get("mid") or 0), 2),
            str(row.get("price_source")),
        )
    from services.chain_provider import resolve_sale_price
    bid = float(row.get("bid") or 0)
    ask = float(row.get("ask") or 0)
    return resolve_sale_price(bid, ask)

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    logger.warning("yfinance not available — using Yahoo Finance JSON API fallback")

DEFAULT_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    # Mid/large-cap tech & semiconductors
    "AMD", "INTC", "QCOM", "MU", "LRCX", "KLAC", "MRVL", "TXN", "AMAT", "ON",
    # Software / cloud / cybersecurity
    "CRM", "NOW", "ADBE", "PANW", "CRWD", "NET", "SNOW", "DDOG", "ZS", "OKTA",
    "PLTR", "HUBS", "WDAY", "TEAM", "MDB", "CFLT",
    # Consumer / e-commerce / travel
    "UBER", "LYFT", "ABNB", "BKNG", "DASH", "COIN", "RBLX",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC", "V", "MA", "PYPL", "AXP", "BLK",
    # Healthcare
    "JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY", "DHR", "TMO", "ISRG", "CVS",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY",
    # Industrials / defense
    "BA", "CAT", "DE", "LMT", "RTX", "HON", "GE", "ETN",
    # Consumer staples / retail
    "COST", "WMT", "TGT", "HD", "KO", "PEP", "MCD", "SBUX", "NKE",
    # Media / telecom
    "DIS", "NFLX", "CMCSA", "T", "VZ",
    # ETFs (broad market + sector)
    "SPY", "QQQ", "IWM", "GLD", "TLT",
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
# Black-Scholes helpers for real options chain data
# ---------------------------------------------------------------------------

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _historical_volatility(ticker: str, days: int = 30) -> float | None:
    """Annualised historical volatility from recent daily closes. Polygon primary, yfinance fallback."""
    import math
    # Polygon primary
    try:
        from services.polygon_client import get_close_prices
        closes = get_close_prices(ticker, days=max(days * 3, 60))
        if len(closes) >= 10:
            log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i-1] > 0]
            if len(log_returns) >= 5:
                mean = sum(log_returns) / len(log_returns)
                variance = sum((r - mean) ** 2 for r in log_returns) / max(len(log_returns) - 1, 1)
                hv = math.sqrt(variance * 252)
                return hv if 0 < hv < 5.0 else None
    except Exception:
        pass
    # yfinance fallback
    if not _YF_AVAILABLE:
        return None
    try:
        hist = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
        closes_s = hist["Close"]
        if hasattr(closes_s, "columns"):
            closes_s = closes_s.iloc[:, 0]
        closes_s = closes_s.dropna()
        if len(closes_s) < 10:
            return None
        returns = closes_s.pct_change().dropna()
        hv = float(returns.std() * (252 ** 0.5))
        return hv if hv > 0 else None
    except Exception:
        return None


def _bs_call_delta(price: float, strike: float, iv: float, T: float, r: float = 0.045) -> float | None:
    """Call delta via Black-Scholes. Returns value 0–1 (probability shares get called away)."""
    try:
        if T <= 0 or iv <= 0 or price <= 0 or strike <= 0:
            return None
        sigma_sqrtT = iv * math.sqrt(T)
        d1 = (math.log(price / strike) + (r + 0.5 * iv ** 2) * T) / sigma_sqrtT
        return round(_ncdf(d1), 3)
    except Exception:
        return None


def _bs_call_theta_daily(price: float, strike: float, iv: float, T: float, r: float = 0.045) -> float | None:
    """Daily income per share earned by the call SELLER from time decay. Positive = good."""
    try:
        if T <= 0 or iv <= 0 or price <= 0 or strike <= 0:
            return None
        sigma_sqrtT = iv * math.sqrt(T)
        d1 = (math.log(price / strike) + (r + 0.5 * iv ** 2) * T) / sigma_sqrtT
        d2 = d1 - sigma_sqrtT
        npdf_d1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
        theta_annual = (
            -(price * npdf_d1 * iv) / (2 * math.sqrt(T))
            - r * strike * math.exp(-r * T) * _ncdf(d2)
        )
        return round(-theta_annual / 365.0, 4)
    except Exception:
        return None


def _bs_put_delta(price: float, strike: float, iv: float, T: float, r: float = 0.045) -> float | None:
    """Put delta via Black-Scholes. iv is annual vol as fraction (0.28 = 28%)."""
    try:
        if T <= 0 or iv <= 0 or price <= 0 or strike <= 0:
            return None
        sigma_sqrtT = iv * math.sqrt(T)
        d1 = (math.log(price / strike) + (r + 0.5 * iv ** 2) * T) / sigma_sqrtT
        return round(_ncdf(d1) - 1.0, 3)   # negative for puts
    except Exception:
        return None


def _bs_put_theta_daily(price: float, strike: float, iv: float, T: float, r: float = 0.045) -> float | None:
    """
    Daily income per share earned by the put SELLER from time decay.
    Positive value = seller collects this per share per day just from time passing.
    """
    try:
        if T <= 0 or iv <= 0 or price <= 0 or strike <= 0:
            return None
        sigma_sqrtT = iv * math.sqrt(T)
        d1 = (math.log(price / strike) + (r + 0.5 * iv ** 2) * T) / sigma_sqrtT
        d2 = d1 - sigma_sqrtT
        npdf_d1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
        # BS annual theta for put: -(S*N'(d1)*σ)/(2√T) + r*K*e^{-rT}*N(-d2)
        theta_annual = (
            -(price * npdf_d1 * iv) / (2 * math.sqrt(T))
            + r * strike * math.exp(-r * T) * _ncdf(-d2)
        )
        # Seller receives the decay: positive, daily per share
        return round(-theta_annual / 365.0, 4)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Finnhub OHLCV helper — primary data source
# ---------------------------------------------------------------------------

def _finnhub_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV via Finnhub candles, returned as a DataFrame matching yfinance format."""
    try:
        from services.finnhub_client import get_candles
        days = {"1mo": 35, "3mo": 95, "6mo": 185, "1y": 375, "2y": 755}.get(period, 375)
        candles = get_candles(ticker, days=days)
        if candles.get("s") != "ok" or not candles.get("c"):
            return pd.DataFrame()
        df = pd.DataFrame({
            "Open":   candles.get("o", [None] * len(candles["c"])),
            "High":   candles.get("h", [None] * len(candles["c"])),
            "Low":    candles.get("l", [None] * len(candles["c"])),
            "Close":  candles["c"],
            "Volume": candles.get("v", [0] * len(candles["c"])),
        }, index=pd.to_datetime(candles["t"], unit="s")).dropna(subset=["Close"])
        return df
    except Exception as e:
        logger.debug("Finnhub history error for %s: %s", ticker, e)
        return pd.DataFrame()


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

# Why the most recent get_put_tiers call returned None, composed from the
# chain provider's per-source notes, so the API can surface the real cause
# (provider error, empty chain, filtered rows) instead of a generic line.
_LAST_CHAIN_ERROR: str | None = None


def get_last_chain_error() -> str | None:
    """Return the recorded reason for the last failed tiers lookup."""
    return _LAST_CHAIN_ERROR


class StockDataService:

    def _get_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Return OHLCV DataFrame. Finnhub primary; yfinance per-ticker fallback."""
        df = _finnhub_history(ticker, period)
        if not df.empty:
            return df
        if _YF_AVAILABLE:
            try:
                df = yf.Ticker(ticker).history(period=period)
                if not df.empty:
                    return df
            except Exception:
                pass
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
        result = {}
        for ticker in tickers:
            # Try Polygon first for live IV
            try:
                from services.polygon_client import get_options_chain_snapshot
                snaps = get_options_chain_snapshot(ticker, dte_max=7)
                if snaps:
                    price = None
                    for s in snaps:
                        if s.underlying_asset and s.underlying_asset.price:
                            price = float(s.underlying_asset.price)
                            break
                    if price:
                        atm = min(
                            (s for s in snaps if s.details and s.implied_volatility and s.details.contract_type == "call"),
                            key=lambda s: abs(float(s.details.strike_price or 0) - price),
                            default=None,
                        )
                        if atm and atm.implied_volatility:
                            iv = round(float(atm.implied_volatility) * 100, 1)
                            expiry = str(atm.details.expiration_date)
                            result[ticker] = {
                                "nearest_expiry": expiry,
                                "atm_iv": iv,
                                "iv_rank_approx": min(100, round(iv / 0.5, 1)),
                                "data_source": "polygon_live",
                            }
                            continue
            except Exception:
                pass

            # yfinance fallback
            if not _YF_AVAILABLE:
                continue
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
                from services.finnhub_client import get_basic_financials, get_company_profile
                metrics = get_basic_financials(ticker)
                profile = get_company_profile(ticker)
                if metrics or profile:
                    result[ticker] = {
                        "pe_ratio": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
                        "eps_growth_ttm": metrics.get("epsGrowthTTMYoy"),
                        "revenue_growth_ttm": metrics.get("revenueGrowthTTMYoy"),
                        "div_yield": metrics.get("dividendYieldIndicatedAnnual"),
                        "sector": profile.get("finnhubIndustry", "Unknown"),
                        "analyst_rating": None,
                        "52w_high": metrics.get("52WeekHigh"),
                        "52w_low": metrics.get("52WeekLow"),
                    }
                    continue
            except Exception as e:
                logger.debug("Finnhub fundamentals error for %s: %s", ticker, e)
            # Fallback: yfinance per-ticker
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
                logger.debug("Fundamentals fallback error for %s: %s", ticker, e)
        return result

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            from services.finnhub_client import get_quote
            q = get_quote(ticker)
            if q.get("c"):
                return float(q["c"])
        except Exception:
            pass
        try:
            if _YF_AVAILABLE:
                return float(yf.Ticker(ticker).fast_info.last_price)
        except Exception:
            pass
        try:
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

    def _polygon_options_chain(
        self, ticker: str, contract_type: str, dte_min: int, dte_max: int,
        near_price: float | None = None,
    ) -> tuple[list[dict], float | None]:
        """Delegates to ChainProvider._fetch_polygon_rows. Kept for backward compatibility."""
        from services.chain_provider import ChainProvider
        return ChainProvider()._fetch_polygon_rows(
            ticker, contract_type, dte_min, dte_max, near_price=near_price
        )

    def get_put_tiers(self, ticker: str) -> dict | None:
        """
        Fetch real put options chain and return three tiers for wheel strategy analysis.
        Uses Polygon real-time data (with Greeks) when available; falls back to yfinance.
        """
        global _LAST_CHAIN_ERROR
        _LAST_CHAIN_ERROR = None
        from services.chain_provider import ChainProvider
        provider = ChainProvider()

        # Polygon primary
        live_price = provider.fetch_price(ticker)
        puts, price = provider._fetch_polygon_rows(ticker, "put", 14, 45, near_price=live_price)
        is_polygon = bool(puts and price)

        if not is_polygon:
            yf_rows, yf_price, yf_source = provider._fetch_yfinance_rows(ticker, "put", 14, 45)
            if not yf_rows or not yf_price:
                _LAST_CHAIN_ERROR = (
                    f"{provider.last_polygon_note}; {provider.last_yfinance_note}"
                )
                return None
            puts = yf_rows
            price = yf_price
            data_source = "live" if yf_source == "yfinance_live" else "last_trade"
        else:
            data_source = "polygon_live"

        today = date.today()
        expiries = sorted(set(p["expiry"] for p in puts))
        if is_polygon:
            target_expiry = min(expiries, key=lambda e: abs((date.fromisoformat(e) - today).days - 21))
        else:
            target_expiry = expiries[0]
        puts = [p for p in puts if p["expiry"] == target_expiry]
        if not puts:
            _LAST_CHAIN_ERROR = "chain rows existed but none at the target expiry"
            return None
        dte = (date.fromisoformat(target_expiry) - today).days
        atm = min(puts, key=lambda p: abs(p["strike"] - price))
        atm_iv_pct = atm["iv_pct"]

        def _tier(target_delta_abs: float) -> dict | None:
            best = min(puts, key=lambda p: abs(p["delta_abs"] - target_delta_abs))
            if is_polygon and abs(best["delta_abs"] - target_delta_abs) > 0.15:
                return None
            # Wheel put sales are priced at the bid, what the seller
            # collects. TXN Nov 13 $270 put: bid $1.55, mid $2.50, last
            # trade $5.00. premium_per_contract is bid x 100 ($155) and
            # breakeven is strike minus the bid ($268.45), never the
            # last-trade $500 / $265.00. A tier with no executable bid
            # carries sale_price 0 and premium_source
            # "no_executable_bid"; the wheel scanner excludes it.
            sale_price, mid, price_source = _sale_price_for_row(best)
            strike = best["strike"]
            breakeven = round(strike - sale_price, 2) if sale_price > 0 else None
            drop_pct = round((price - breakeven) / price * 100, 1) if breakeven else None
            ann_return = round((sale_price / strike) * (365 / dte) * 100, 1) if strike > 0 and dte > 0 and sale_price > 0 else None
            daily_income = round((best["theta_seller"] or 0) * 100, 2)
            return {
                "strike": strike,
                "expiry": target_expiry,
                "dte": dte,
                "bid": best["bid"],
                "ask": best["ask"],
                "mid_premium": mid,
                "sale_price": sale_price,
                "premium_source": price_source,
                "premium_per_contract": round(sale_price * 100, 2),
                "iv_pct": best["iv_pct"],
                "delta_abs": round(best["delta_abs"], 2),
                "assignment_chance_pct": round(best["delta_abs"] * 100),
                "daily_income_per_contract": daily_income,
                "breakeven": breakeven,
                "drop_to_breakeven_pct": drop_pct,
                "annualized_return_pct": ann_return,
                "volume": best["volume"],
                "open_interest": best["open_interest"],
            }

        return {
            "current_price": round(price, 2),
            "expiry": target_expiry,
            "dte": dte,
            "atm_iv_pct": atm_iv_pct,
            "data_source": data_source,
            "likely": _tier(0.45),
            "moderate": _tier(0.30),
            "unlikely": _tier(0.16),
        }

    def snap_put_strike(self, ticker: str, suggested_strike: float, prefer_dte: tuple = (14, 45)) -> dict | None:
        """
        Given Claude's suggested put strike, snap to the nearest real tradeable strike.
        Uses Polygon real-time data when available; falls back to yfinance.
        """
        min_dte, max_dte = prefer_dte
        # --- Polygon path (preferred) ---
        try:
            puts, price = self._polygon_options_chain(
                ticker, "put", min_dte, max_dte, near_price=suggested_strike
            )
            if puts:
                best = min(puts, key=lambda p: abs(p["strike"] - suggested_strike))
                sale_price, mid, price_source = _sale_price_for_row(best)
                return {
                    "strike": best["strike"],
                    "expiry": best["expiry"],
                    "dte": best["dte"],
                    "mid_premium": mid,
                    "sale_price": sale_price,
                    "premium_source": price_source,
                    "bid": best["bid"],
                    "ask": best["ask"],
                    "volume": best["volume"],
                    "open_interest": best["open_interest"],
                }
        except Exception as e:
            logger.debug("snap_put_strike Polygon path failed for %s: %s", ticker, e)

        # --- yfinance fallback ---
        if not _YF_AVAILABLE:
            return None
        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return None

            today = date.today()
            min_dte, max_dte = prefer_dte
            target_expiry = None
            for exp in expiries:
                days = (date.fromisoformat(exp) - today).days
                if min_dte <= days <= max_dte:
                    target_expiry = exp
                    break
            if not target_expiry:
                for exp in expiries:
                    if (date.fromisoformat(exp) - today).days >= 7:
                        target_expiry = exp
                        break
            if not target_expiry:
                return None

            chain = t.option_chain(target_expiry)
            puts = chain.puts.copy()
            if puts.empty:
                return None

            # Find nearest real strike to suggested
            nearest_idx = (puts["strike"] - suggested_strike).abs().idxmin()
            row = puts.loc[nearest_idx]
            strike = float(row["strike"])
            bid = float(row.get("bid") or 0)
            ask = float(row.get("ask") or 0)
            # Executable mid only. A last trade is never the premium:
            # "mid = (bid + ask) / 2 if bid > 0 else last" used to price
            # sales at a stale last trade. The sale price is the bid.
            from services.chain_provider import resolve_sale_price
            sale_price, mid, price_source = resolve_sale_price(bid, ask)

            dte = (date.fromisoformat(target_expiry) - today).days
            return {
                "strike": strike,
                "expiry": target_expiry,
                "dte": dte,
                "mid_premium": mid,
                "sale_price": sale_price,
                "premium_source": price_source,
                "bid": bid,
                "ask": ask,
                "volume": int(row.get("volume") or 0),
                "open_interest": int(row.get("openInterest") or 0),
            }
        except Exception as e:
            logger.debug("snap_put_strike failed for %s: %s", ticker, e)
            return None


    def get_call_tiers(self, ticker: str) -> dict | None:
        """
        Fetch call options chain for covered call income strategy.
        Returns three tiers: aggressive, balanced, conservative.
        Uses Polygon real-time data (with Greeks) when available; falls back to yfinance.
        """
        from services.chain_provider import ChainProvider
        provider = ChainProvider()

        # Polygon primary
        live_price = provider.fetch_price(ticker)
        calls, price = provider._fetch_polygon_rows(ticker, "call", 4, 30, near_price=live_price)
        is_polygon = bool(calls and price)

        if not is_polygon:
            yf_rows, yf_price, yf_source = provider._fetch_yfinance_rows(ticker, "call", 4, 30)
            if yf_rows and yf_price:
                calls = yf_rows
                price = yf_price
                data_source = "live" if yf_source == "yfinance_live" else "last_trade"
            else:
                calls = []
                price = None
                data_source = None
        else:
            data_source = "polygon_live"

        if calls and price:
            today = date.today()
            expiries = sorted(set(c["expiry"] for c in calls))
            if is_polygon:
                target_expiry = min(expiries, key=lambda e: abs((date.fromisoformat(e) - today).days - 14))
            else:
                target_expiry = expiries[0]
            calls = [c for c in calls if c["expiry"] == target_expiry]
            if not calls:
                calls = []
            else:
                dte = (date.fromisoformat(target_expiry) - today).days
                atm = min(calls, key=lambda c: abs(c["strike"] - price))
                atm_iv_pct = atm["iv_pct"]
                options_type = "weekly" if dte <= 14 else "monthly"
                weeks = dte / 7.0
                min_premium = round(price * 0.003 * weeks, 2)

                def _call_tier(target_delta: float) -> dict | None:
                    sane = [c for c in calls if 0.8 * price <= c["strike"] <= 3.0 * price]
                    pool = sane if sane else calls
                    best = min(pool, key=lambda c: abs(c["delta"] - target_delta))
                    if is_polygon and abs(best["delta"] - target_delta) > 0.20:
                        return None
                    # Covered-call sales are priced at the bid, same rule
                    # as put sales: a last trade is never the premium.
                    sale_price, mid, price_source = _sale_price_for_row(best)
                    strike = best["strike"]
                    daily_income = round((best["theta_seller"] or 0) * 100, 2)
                    upside_pct = round((strike - price) / price * 100, 1)
                    pct_of_stock = round(sale_price / price * 100, 2) if sale_price > 0 else 0
                    return {
                        "strike": strike,
                        "expiry": target_expiry,
                        "dte": dte,
                        "bid": best["bid"],
                        "ask": best["ask"],
                        "mid_premium": mid,
                        "sale_price": sale_price,
                        "premium_source": price_source,
                        "premium_per_contract": round(sale_price * 100, 2),
                        "iv_pct": best["iv_pct"],
                        "delta": round(best["delta"], 2),
                        "call_away_chance_pct": round(best["delta"] * 100),
                        "daily_income_per_contract": daily_income,
                        "upside_to_strike_pct": upside_pct,
                        "pct_of_stock_weekly": pct_of_stock,
                        "below_threshold": sale_price < min_premium,
                        "volume": best["volume"],
                        "open_interest": best["open_interest"],
                    }

                return {
                    "current_price": round(price, 2),
                    "expiry": target_expiry,
                    "dte": dte,
                    "options_type": options_type,
                    "atm_iv_pct": atm_iv_pct,
                    "data_source": data_source,
                    "min_premium_threshold": min_premium,
                    "aggressive": _call_tier(0.70),
                    "balanced": _call_tier(0.45),
                    "conservative": _call_tier(0.20),
                }

        # --- Synthetic Black-Scholes fallback ---
        # Runs when Polygon (no Options subscription) and yfinance (rate-limited on cloud) both fail.
        # Prices synthetic options using _historical_volatility (Polygon primary) and Black-Scholes.
        try:
            _live_price = provider.fetch_price(ticker)
            if not _live_price:
                return None
            price = _live_price

            hv: float = 0.30
            hv_computed = _historical_volatility(ticker)
            if hv_computed:
                hv = hv_computed

            from datetime import timedelta
            today = date.today()
            days_to_friday = (4 - today.weekday()) % 7
            if days_to_friday < 3:
                days_to_friday += 7
            target_expiry = (today + timedelta(days=days_to_friday)).isoformat()
            dte = days_to_friday
            T = max(dte, 1) / 365.0
            options_type = "weekly" if dte <= 14 else "monthly"
            min_premium = round(price * 0.003 * dte / 7.0, 2)

            rounding = 0.5 if price < 50 else (5.0 if price > 500 else 1.0)
            strikes = sorted(set(
                round(price * m / rounding) * rounding
                for m in [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
            ))

            r = 0.045
            synthetic_calls = []
            for strike in strikes:
                if strike <= 0:
                    continue
                delta = _bs_call_delta(price, strike, hv, T, r)
                theta = _bs_call_theta_daily(price, strike, hv, T, r)
                if delta is None:
                    continue
                sigma_sqrtT = hv * math.sqrt(T)
                d1 = (math.log(price / strike) + (r + 0.5 * hv ** 2) * T) / sigma_sqrtT
                d2 = d1 - sigma_sqrtT
                bs_price = round(max(price * _ncdf(d1) - strike * math.exp(-r * T) * _ncdf(d2), 0.01), 2)
                spread = round(max(bs_price * 0.10, 0.05), 2)
                synthetic_calls.append({
                    "strike": strike,
                    "mid": bs_price,
                    "bid": round(max(bs_price - spread / 2, 0.01), 2),
                    "ask": round(bs_price + spread / 2, 2),
                    "delta": delta,
                    "theta": theta,
                })

            if not synthetic_calls:
                return None

            atm_iv_pct = round(hv * 100, 1)

            def _synth_tier(target_delta: float) -> dict | None:
                best = min(synthetic_calls, key=lambda c: abs(c["delta"] - target_delta))
                # Synthetic rows carry a modelled bid/ask around the BS
                # price, so the sale price is still the bid.
                sale_price, mid, price_source = _sale_price_for_row(best)
                strike = best["strike"]
                delta_val = best["delta"]
                theta = best["theta"]
                daily_per_contract = round(float(theta) * 100, 2) if theta else None
                return {
                    "strike": strike,
                    "expiry": target_expiry,
                    "dte": dte,
                    "bid": best["bid"],
                    "ask": best["ask"],
                    "mid_premium": mid,
                    "sale_price": sale_price,
                    "premium_source": price_source,
                    "premium_per_contract": round(sale_price * 100, 2),
                    "iv_pct": atm_iv_pct,
                    "delta": round(delta_val, 2),
                    "call_away_chance_pct": round(delta_val * 100),
                    "daily_income_per_contract": daily_per_contract,
                    "upside_to_strike_pct": round((strike - price) / price * 100, 1),
                    "pct_of_stock_weekly": round(sale_price / price * 100, 2),
                    "below_threshold": sale_price < min_premium,
                    "volume": 0,
                    "open_interest": 0,
                }

            logger.info("get_call_tiers synthetic BS for %s: price=%.2f hv=%.2f dte=%d", ticker, price, hv, dte)
            return {
                "current_price": round(price, 2),
                "expiry": target_expiry,
                "dte": dte,
                "options_type": options_type,
                "atm_iv_pct": atm_iv_pct,
                "data_source": "synthetic_bs",
                "min_premium_threshold": min_premium,
                "aggressive": _synth_tier(0.70),
                "balanced": _synth_tier(0.45),
                "conservative": _synth_tier(0.20),
            }
        except Exception as e:
            logger.warning("get_call_tiers synthetic BS failed for %s: %s", ticker, e)
            return None

    def get_weekly_call_tiers(self, ticker: str) -> dict | None:
        """
        Fetch call options targeting the NEAREST expiry (this week or next, <=9 DTE).
        Used for the weekly covered call scanner. Falls back to the standard 14-DTE
        expiry if no near-term options exist.
        """
        from services.chain_provider import ChainProvider
        provider = ChainProvider()

        def _build_tiers(calls, price, target_expiry, data_source):
            today = date.today()
            dte = (date.fromisoformat(target_expiry) - today).days
            atm = min(calls, key=lambda c: abs(c["strike"] - price))
            atm_iv_pct = atm["iv_pct"]
            weeks = max(dte / 7.0, 0.2)
            min_premium = round(price * 0.003 * weeks, 2)

            def _tier(target_delta):
                sane = [c for c in calls if 0.8 * price <= c["strike"] <= 3.0 * price]
                pool = sane if sane else calls
                best = min(pool, key=lambda c: abs(c["delta"] - target_delta))
                if abs(best["delta"] - target_delta) > 0.20:
                    return None
                sale_price, mid, price_source = _sale_price_for_row(best)
                strike = best["strike"]
                pct_of_stock = round(sale_price / price * 100, 2) if sale_price > 0 else 0
                return {
                    "strike": strike,
                    "expiry": target_expiry,
                    "dte": dte,
                    "bid": best["bid"],
                    "ask": best["ask"],
                    "mid_premium": mid,
                    "sale_price": sale_price,
                    "premium_source": price_source,
                    "premium_per_contract": round(sale_price * 100, 2),
                    "iv_pct": best["iv_pct"],
                    "delta": round(best["delta"], 2),
                    "call_away_chance_pct": round(best["delta"] * 100),
                    "daily_income_per_contract": round((best["theta_seller"] or 0) * 100, 2),
                    "upside_to_strike_pct": round((strike - price) / price * 100, 1),
                    "pct_of_stock_weekly": pct_of_stock,
                    "below_threshold": sale_price < min_premium,
                    "volume": best["volume"],
                    "open_interest": best["open_interest"],
                }

            return {
                "current_price": round(price, 2),
                "expiry": target_expiry,
                "dte": dte,
                "options_type": "weekly",
                "atm_iv_pct": atm_iv_pct,
                "data_source": data_source,
                "min_premium_threshold": min_premium,
                "aggressive": _tier(0.70),
                "balanced": _tier(0.45),
                "conservative": _tier(0.20),
            }

        # Polygon-only retry: 0-9 DTE first, then 0-16 DTE
        today = date.today()
        for max_dte in (9, 16):
            rows, price = provider._fetch_polygon_rows(ticker, "call", 0, max_dte)
            if rows and price:
                expiries = sorted(set(c["expiry"] for c in rows))
                target_expiry = min(expiries, key=lambda e: (date.fromisoformat(e) - today).days)
                week_calls = [c for c in rows if c["expiry"] == target_expiry]
                if week_calls:
                    return _build_tiers(week_calls, price, target_expiry, "polygon_live")

        # yfinance fallback: nearest expiry within 0-16 DTE
        yf_rows, yf_price, yf_source = provider._fetch_yfinance_rows(ticker, "call", 0, 16)
        if not yf_rows or not yf_price:
            return None
        data_source = "live" if yf_source == "yfinance_live" else "last_trade"
        expiries = sorted(set(c["expiry"] for c in yf_rows))
        target_expiry = expiries[0]
        return _build_tiers(yf_rows, yf_price, target_expiry, data_source)

    def get_chain_context(self, tickers: list[str]) -> dict:
        """
        For each ticker return a compact real-market options chain string.
        Used to give Claude actual bid/ask prices instead of BS estimates.
        """
        if not _YF_AVAILABLE:
            return {}
        result = {}
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                expiries = t.options
                if not expiries:
                    continue
                info = t.fast_info
                price = getattr(info, "last_price", None)
                if not price:
                    continue

                chain = t.option_chain(expiries[0])
                calls = chain.calls[chain.calls["bid"] > 0].copy()
                puts = chain.puts[chain.puts["bid"] > 0].copy()

                def _nearby(df, n_below=1, n_above=2):
                    if df.empty:
                        return df
                    atm_label = (df["strike"] - price).abs().idxmin()
                    atm_iloc = df.index.get_loc(atm_label)
                    return df.iloc[max(0, atm_iloc - n_below): atm_iloc + n_above + 1]

                call_rows = _nearby(calls, 0, 3)
                put_rows = _nearby(puts, 2, 1)

                def _fmt_row(row, suffix):
                    iv = round(float(row["impliedVolatility"]) * 100)
                    return f"{int(row['strike'])}{suffix} ${row['bid']:.2f}/${row['ask']:.2f} IV={iv}%"

                call_str = " | ".join(_fmt_row(r, "C") for _, r in call_rows.iterrows())
                put_str = " | ".join(_fmt_row(r, "P") for _, r in put_rows.iterrows())

                result[ticker] = {
                    "expiry": expiries[0],
                    "calls": call_str or "n/a",
                    "puts": put_str or "n/a",
                }
            except Exception as e:
                logger.debug("chain_context error for %s: %s", ticker, e)
        return result


# ---------------------------------------------------------------------------
# Convenience helper for watchlist / one-off scoring
# ---------------------------------------------------------------------------

def get_stock_info(ticker: str) -> dict:
    """Return a flat dict of price, technicals, and fundamentals for one ticker."""
    try:
        # OHLCV: Finnhub primary, Yahoo HTTP fallback
        df = _finnhub_history(ticker, "1y")
        if df.empty:
            df = _yf_fetch_ohlcv(ticker, period_days=252)
        price = float(df["Close"].iloc[-1]) if not df.empty else None
        indicators = _compute_all_indicators(df) if not df.empty else {}

        # Fundamentals + earnings: Finnhub primary
        summary: dict = {}
        earnings_date: str | None = None
        try:
            from services.finnhub_client import (
                get_basic_financials, get_company_profile, get_earnings_this_month
            )
            metrics = get_basic_financials(ticker)
            profile = get_company_profile(ticker)
            summary = {
                "pe_ratio": metrics.get("peNormalizedAnnual") or metrics.get("peTTM"),
                "div_yield": metrics.get("dividendYieldIndicatedAnnual"),
                "sector": profile.get("finnhubIndustry", ""),
                "analyst_rating": None,
                "52w_high": metrics.get("52WeekHigh"),
                "52w_low": metrics.get("52WeekLow"),
            }
            days_away = get_earnings_this_month(ticker)
            if days_away is not None:
                from datetime import date, timedelta
                earnings_date = (date.today() + timedelta(days=days_away)).isoformat()
        except Exception as e:
            logger.debug("Finnhub info error for %s: %s", ticker, e)
            summary = _yf_fetch_summary(ticker)

        return {
            "ticker": ticker,
            "price": round(price, 2) if price else None,
            "current_price": round(price, 2) if price else None,
            "rsi": indicators.get("rsi"),
            "ma50": indicators.get("moving_averages", {}).get("ma50"),
            "ma200": indicators.get("moving_averages", {}).get("ma200"),
            "pe_ratio": summary.get("pe_ratio"),
            "div_yield": summary.get("div_yield"),
            "sector": summary.get("sector"),
            "analyst_rating": summary.get("analyst_rating"),
            "52w_high": summary.get("52w_high"),
            "52w_low": summary.get("52w_low"),
            "earnings_date": earnings_date,
        }
    except Exception as e:
        logger.warning("get_stock_info failed for %s: %s", ticker, e)
        return {"ticker": ticker}
