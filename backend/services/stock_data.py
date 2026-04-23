import logging
import json
import math
from datetime import date
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

    def get_put_tiers(self, ticker: str) -> dict | None:
        """
        Fetch real put options chain and return three tiers for wheel strategy analysis.
        Tiers are based on assignment probability (delta), with real bid/ask from yfinance.
        Returns None if options data is unavailable.
        """
        if not _YF_AVAILABLE:
            return None
        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return None

            # Prefer expiry 14-45 days out — best premium-to-risk ratio for wheel
            today = date.today()
            target_expiry = None
            for exp in expiries:
                days = (date.fromisoformat(exp) - today).days
                if 14 <= days <= 45:
                    target_expiry = exp
                    break
            if not target_expiry:
                target_expiry = expiries[0]

            info = t.fast_info
            price = getattr(info, "last_price", None)
            if not price:
                return None

            chain = t.option_chain(target_expiry)
            puts = chain.puts.copy()
            if puts.empty:
                return None

            exp_date = date.fromisoformat(target_expiry)
            T = max((exp_date - today).days, 1) / 365.0
            dte = (exp_date - today).days

            # Use real bid/ask when markets are open; fall back to lastPrice when closed.
            # This lets the feature work evenings, weekends, and pre/post market.
            puts["_mid"] = puts.apply(
                lambda r: round((float(r["bid"]) + float(r["ask"])) / 2, 2)
                          if float(r["bid"]) > 0
                          else float(r.get("lastPrice", 0) or 0),
                axis=1,
            )
            puts["_is_live"] = puts["bid"] > 0
            puts = puts[puts["_mid"] > 0].copy()
            if puts.empty:
                return None

            data_source = "live" if puts["_is_live"].any() else "last_trade"

            # Compute delta and daily theta for each put using per-strike IV
            puts["_delta"] = puts.apply(
                lambda r: _bs_put_delta(price, r["strike"], float(r["impliedVolatility"]), T),
                axis=1,
            )
            puts["_theta_daily"] = puts.apply(
                lambda r: _bs_put_theta_daily(price, r["strike"], float(r["impliedVolatility"]), T),
                axis=1,
            )
            puts = puts[puts["_delta"].notna()].copy()
            puts["_delta_abs"] = puts["_delta"].abs()

            # ATM IV for context (put closest to current price)
            atm_idx = (puts["strike"] - price).abs().idxmin()
            atm_row = puts.loc[atm_idx]
            atm_iv_pct = round(float(atm_row["impliedVolatility"]) * 100, 1)

            def _best_near_delta(target: float) -> dict | None:
                if puts.empty:
                    return None
                idx = (puts["_delta_abs"] - target).abs().idxmin()
                row = puts.loc[idx]
                mid = float(row["_mid"])   # uses lastPrice when bid=0 (markets closed)
                bid = float(row["bid"]) if float(row["bid"]) > 0 else mid
                ask = float(row["ask"]) if float(row["ask"]) > 0 else mid
                strike = float(row["strike"])
                iv_pct = round(float(row["impliedVolatility"]) * 100, 1)
                delta_abs = round(float(row["_delta_abs"]), 2)
                theta = row["_theta_daily"]
                daily_per_contract = round(float(theta) * 100, 2) if theta else None
                breakeven = round(strike - mid, 2)
                drop_pct = round((price - breakeven) / price * 100, 1)
                ann_return = round((mid / strike) * (365 / dte) * 100, 1)
                return {
                    "strike": strike,
                    "expiry": target_expiry,
                    "dte": dte,
                    "bid": bid,
                    "ask": ask,
                    "mid_premium": mid,
                    "premium_per_contract": round(mid * 100, 2),
                    "iv_pct": iv_pct,
                    "delta_abs": delta_abs,
                    "assignment_chance_pct": round(delta_abs * 100),
                    "daily_income_per_contract": daily_per_contract,
                    "breakeven": breakeven,
                    "drop_to_breakeven_pct": drop_pct,
                    "annualized_return_pct": ann_return,
                    "volume": int(row.get("volume", 0) or 0),
                    "open_interest": int(row.get("openInterest", 0) or 0),
                }

            return {
                "current_price": round(price, 2),
                "expiry": target_expiry,
                "dte": dte,
                "atm_iv_pct": atm_iv_pct,
                "data_source": data_source,
                "likely": _best_near_delta(0.45),
                "moderate": _best_near_delta(0.30),
                "unlikely": _best_near_delta(0.16),
            }
        except Exception as e:
            logger.warning("get_put_tiers failed for %s: %s", ticker, e)
            return None

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
