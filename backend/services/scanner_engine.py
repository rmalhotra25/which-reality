"""
Day Trade Scanner — yfinance-based universe scan with technical indicators.

Flow:
1. Fetch market status from Massive (free tier)
2. Batch-download 30d of OHLCV for a curated 150-stock universe + SPY via yfinance
3. Compute RSI-14, ATR-14, and relative strength vs SPY for each ticker
4. Filter for biggest movers by % change and volume surge
5. Enrich top candidates with news headlines from Massive (free tier)
6. Pass enriched candidates to Claude for high-confidence play selection
"""
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

MIN_PRICE = 5.0
MAX_PRICE = 600.0
MIN_VOLUME = 200_000
MIN_CHANGE_PCT = 1.5

SCAN_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "ORCL",
    # Semiconductors
    "AMD", "INTC", "QCOM", "TXN", "MU", "SMCI", "ARM",
    # Financials
    "JPM", "BAC", "GS", "MS", "V", "MA", "PYPL", "SQ",
    # High-IV momentum / retail favorites
    "PLTR", "COIN", "HOOD", "SOFI", "RIVN", "SHOP", "SNAP", "UBER", "LYFT",
    "MSTR", "RBLX", "DUOL", "DKNG", "PENN",
    # Biotech / pharma
    "LLY", "ABBV", "PFE", "MRNA", "BNTX", "REGN", "BIIB", "GILD",
    # Energy
    "XOM", "CVX", "OXY", "SLB", "HAL",
    # Consumer / retail
    "COST", "HD", "WMT", "NKE", "MCD", "SBUX", "CMG",
    # Media / streaming
    "NFLX", "DIS", "SPOT", "ROKU",
    # Software / cloud
    "CRM", "NOW", "ADBE", "SNOW", "DDOG", "ZM", "OKTA", "CRWD", "S",
    # EV / clean energy
    "RIVN", "LCID", "NIO", "XPEV", "LI", "PLUG", "FSLR",
    # Other high-volume
    "F", "GM", "BA", "GE", "T", "VZ", "C", "WFC",
    # ETFs with options + high volume
    "SPY", "QQQ", "IWM", "ARKK", "XLE", "GLD", "SLV", "SOXL", "TQQQ", "SQQQ",
]
# Deduplicate while preserving order
_seen = set()
SCAN_UNIVERSE = [t for t in SCAN_UNIVERSE if not (t in _seen or _seen.add(t))]


def _rsi(prices: pd.Series, period: int = 14) -> float | None:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if pd.notna(val) else None


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    val = atr.iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def _ma(prices: pd.Series, period: int) -> float | None:
    if len(prices) < period:
        return None
    val = prices.rolling(period).mean().iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def _fetch_movers() -> tuple[list[dict], float | None]:
    """Download 30d of OHLCV for the universe + SPY, compute technicals, return movers + SPY change."""
    tickers_to_fetch = list(dict.fromkeys(["SPY"] + SCAN_UNIVERSE))
    try:
        raw = yf.download(
            tickers_to_fetch,
            period="30d",
            interval="1d",
            progress=False,
            threads=True,
            auto_adjust=True,
        )
    except Exception as e:
        logger.error("yfinance batch download failed: %s", e)
        return [], None

    # Compute SPY's today-vs-yesterday change for relative strength
    spy_change = None
    try:
        spy_close = raw["Close"]["SPY"].dropna()
        if len(spy_close) >= 2:
            spy_change = round((float(spy_close.iloc[-1]) - float(spy_close.iloc[-2])) / float(spy_close.iloc[-2]) * 100, 2)
    except Exception:
        pass

    candidates = []
    for ticker in SCAN_UNIVERSE:
        try:
            close = raw["Close"][ticker].dropna()
            volume = raw["Volume"][ticker].dropna()
            high = raw["High"][ticker].dropna()
            low = raw["Low"][ticker].dropna()
            open_ = raw["Open"][ticker].dropna()

            if len(close) < 2 or len(volume) < 2:
                continue

            price = float(close.iloc[-1])
            prev_close = float(close.iloc[-2])
            vol_today = float(volume.iloc[-1])
            vol_prev = float(volume.iloc[-2]) if len(volume) >= 2 else vol_today

            if price < MIN_PRICE or price > MAX_PRICE:
                continue
            if vol_today < MIN_VOLUME:
                continue

            change_pct = (price - prev_close) / prev_close * 100
            if abs(change_pct) < MIN_CHANGE_PCT:
                continue

            vol_ratio = round(vol_today / vol_prev, 1) if vol_prev > 0 else 1.0
            day_high = float(high.iloc[-1])
            day_low = float(low.iloc[-1])
            day_open = float(open_.iloc[-1])
            vwap = round((day_high + day_low + price) / 3, 2)

            rsi = _rsi(close)
            atr = _atr(high, low, close)
            ma20 = _ma(close, 20)
            vs_spy = round(change_pct - spy_change, 2) if spy_change is not None else None

            # 52-week context: how far from 52-week high/low?
            hi52 = round(float(high.max()), 2) if len(high) >= 50 else None
            lo52 = round(float(low.min()), 2) if len(low) >= 50 else None

            candidates.append({
                "ticker": ticker,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "volume_m": round(vol_today / 1_000_000, 1),
                "vol_ratio": vol_ratio,
                "high": round(day_high, 2),
                "low": round(day_low, 2),
                "open": round(day_open, 2),
                "vwap": vwap,
                "prev_close": round(prev_close, 2),
                "direction": "up" if change_pct > 0 else "down",
                "rsi": rsi,
                "atr": atr,
                "ma20": ma20,
                "vs_spy": vs_spy,
                "hi52": hi52,
                "lo52": lo52,
                "days_to_cover": None,
                "short_volume_ratio_pct": None,
            })
        except Exception as e:
            logger.debug("skipping %s: %s", ticker, e)

    return candidates, spy_change


def run_scan() -> dict:
    """Run the day trade scan and return Claude's top plays."""
    from services.claude_analyst import ClaudeAnalyst

    market_status = None
    try:
        from services.polygon_client import get_market_status
        market_status = get_market_status()
    except Exception as e:
        logger.warning("market_status fetch failed: %s", e)

    candidates, spy_change = _fetch_movers()

    if not candidates:
        return {
            "plays": [],
            "candidates_scanned": 0,
            "market_status": market_status,
            "spy_change": spy_change,
            "error": "No qualifying movers found. Market may be closed or all moves are below threshold.",
        }

    # Sort by vol_ratio first (conviction), then by abs change
    candidates.sort(key=lambda x: (x["vol_ratio"], abs(x["change_pct"])), reverse=True)
    top = candidates[:15]

    # Enrich with news headlines from Massive (graceful — free tier)
    for c in top:
        try:
            from services.polygon_client import get_news
            news = get_news(c["ticker"], limit=3)
            c["news"] = [n.get("title", "") for n in news if n.get("title")]
        except Exception:
            c["news"] = []

    analyst = ClaudeAnalyst()
    plays = analyst.scan_day_trades(top, spy_change=spy_change)

    return {
        "plays": plays,
        "candidates_scanned": len(candidates),
        "top_movers": top,
        "market_status": market_status,
        "spy_change": spy_change,
        "data_note": f"Scanned {len(SCAN_UNIVERSE)}-stock universe · yfinance 30-day daily data · RSI + ATR enriched",
    }
