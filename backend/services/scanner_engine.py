"""
Day Trade Scanner — yfinance-based universe scan.

Flow:
1. Fetch market status from Massive (free tier)
2. Batch-download OHLCV for a curated 150-stock universe via yfinance
3. Filter for biggest movers by % change and volume surge
4. Enrich top candidates with news headlines from Massive (free tier)
5. Pass to Claude for high-confidence play selection
"""
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

MIN_PRICE = 5.0
MAX_PRICE = 600.0
MIN_VOLUME = 300_000
MIN_CHANGE_PCT = 2.0

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
    "COST", "HD", "WMT", "NKE", "MCD", "SBUX", "CMG", "AMZN",
    # Media / streaming
    "NFLX", "DIS", "SPOT", "ROKU",
    # Software / cloud
    "CRM", "NOW", "ADBE", "SNOW", "DDOG", "ZM", "OKTA", "CRWD", "S",
    # EV / clean energy
    "RIVN", "LCID", "NIO", "XPEV", "LI", "PLUG", "FSLR",
    # Other high-volume
    "F", "GM", "BA", "GE", "T", "VZ", "NFLX", "C", "WFC",
    # ETFs with options + high volume
    "SPY", "QQQ", "IWM", "ARKK", "XLE", "GLD", "SLV", "SOXL", "TQQQ", "SQQQ",
]
# Deduplicate while preserving order
_seen = set()
SCAN_UNIVERSE = [t for t in SCAN_UNIVERSE if not (t in _seen or _seen.add(t))]


def _fetch_movers() -> list[dict]:
    """Download last 5 days of OHLCV for the universe and find today's biggest movers."""
    try:
        raw = yf.download(
            SCAN_UNIVERSE,
            period="5d",
            interval="1d",
            progress=False,
            threads=True,
            auto_adjust=True,
        )
    except Exception as e:
        logger.error("yfinance batch download failed: %s", e)
        return []

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
            })
        except Exception as e:
            logger.debug("skipping %s: %s", ticker, e)

    return candidates


def run_scan() -> dict:
    """Run the day trade scan and return Claude's top plays."""
    from services.claude_analyst import ClaudeAnalyst

    market_status = None
    try:
        from services.polygon_client import get_market_status
        market_status = get_market_status()
    except Exception as e:
        logger.warning("market_status fetch failed: %s", e)

    candidates = _fetch_movers()

    if not candidates:
        return {
            "plays": [],
            "candidates_scanned": 0,
            "market_status": market_status,
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
        c["days_to_cover"] = None
        c["short_volume_ratio_pct"] = None

    analyst = ClaudeAnalyst()
    plays = analyst.scan_day_trades(top)

    return {
        "plays": plays,
        "candidates_scanned": len(candidates),
        "top_movers": top,
        "market_status": market_status,
        "data_note": f"Scanned {len(SCAN_UNIVERSE)}-stock universe · yfinance daily data",
    }
