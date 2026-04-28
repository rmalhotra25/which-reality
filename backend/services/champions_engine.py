"""
Champions Engine — daily market-open scan.

1. Pre-screens ~50 curated stocks with ONE bulk yfinance download (fast, free).
2. Passes survivors to Claude in ONE batched call.
3. Stores three champion records (wheel / options / longterm) in the DB.
"""
import logging
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE = [
    # Blue chips / Dow components
    "AAPL", "MSFT", "JPM", "JNJ", "KO", "HD", "V", "UNH", "MCD", "WMT",
    # High-IV momentum
    "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "NFLX", "CRM", "SHOP", "PLTR",
    # Solid wheel candidates
    "COST", "PG", "ABT", "MMM", "T", "VZ", "PFE", "XOM", "CVX", "BAC",
    # Growth / income mix
    "ABBV", "LLY", "TMO", "AVGO", "NOW", "ADBE", "QCOM", "TXN", "BMY", "MO",
    # High-volume mid-caps
    "F", "GM", "UBER", "NKE", "SNAP", "SOFI", "COIN", "RIVN", "HOOD", "LYFT",
]

MIN_AVG_VOLUME = 300_000
MIN_PRICE = 3.0
RSI_LOW, RSI_HIGH = 20.0, 80.0


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    try:
        if len(closes) < period + 1:
            return None
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        val = (100 - (100 / (1 + rs))).iloc[-1]
        return round(float(val), 1) if pd.notna(val) else None
    except Exception:
        return None


def prescreen() -> list[dict]:
    """
    Single bulk download → compute RSI → filter basics.
    No per-ticker API calls — completes in ~10-20 seconds.
    """
    logger.info("Champions: bulk downloading %d tickers", len(UNIVERSE))
    try:
        raw = yf.download(
            UNIVERSE,
            period="60d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error("Champions bulk download failed: %s", e)
        return []

    if raw.empty:
        logger.warning("Champions: bulk download returned empty DataFrame")
        return []

    # yfinance returns (field, ticker) MultiIndex for multiple tickers
    if isinstance(raw.columns, pd.MultiIndex):
        try:
            close_df = raw["Close"]
            volume_df = raw["Volume"]
        except KeyError:
            logger.error("Champions: unexpected DataFrame column structure: %s", raw.columns[:10].tolist())
            return []
    else:
        # Single ticker fallback (shouldn't happen with 50 tickers)
        close_df = pd.DataFrame({"SINGLE": raw["Close"]})
        volume_df = pd.DataFrame({"SINGLE": raw["Volume"]})

    survivors = []
    for ticker in UNIVERSE:
        try:
            if ticker not in close_df.columns:
                continue

            closes = close_df[ticker].dropna()
            volumes = volume_df[ticker].dropna() if ticker in volume_df.columns else pd.Series(dtype=float)

            if len(closes) < 20:
                continue

            price = float(closes.iloc[-1])
            avg_vol = float(volumes.tail(20).mean()) if not volumes.empty else 0

            if price < MIN_PRICE:
                continue
            if avg_vol < MIN_AVG_VOLUME:
                continue

            rsi = _rsi(closes)
            if rsi is not None and (rsi < RSI_LOW or rsi > RSI_HIGH):
                continue

            # 52-week context from the data we already have
            high_52w = float(closes.max())
            low_52w = float(closes.min())
            pct_from_high = round((price - high_52w) / high_52w * 100, 1)

            survivors.append({
                "ticker": ticker,
                "price": round(price, 2),
                "avg_vol_m": round(avg_vol / 1_000_000, 1),
                "rsi": rsi,
                "pct_from_high": pct_from_high,
            })
        except Exception as e:
            logger.debug("Champions pre-screen error for %s: %s", ticker, e)

    logger.info("Champions: %d/%d tickers passed pre-screen", len(survivors), len(UNIVERSE))
    return survivors


def run(db) -> None:
    from models.champion import Champion
    from services.claude_analyst import ClaudeAnalyst

    survivors = prescreen()
    if len(survivors) < 3:
        logger.warning("Champions: only %d survivors — need at least 3", len(survivors))
        return

    analyst = ClaudeAnalyst()
    try:
        champions = analyst.pick_champions(survivors)
    except Exception as e:
        logger.error("Champions Claude call failed: %s", e, exc_info=True)
        return

    if not champions or len(champions) < 2:
        logger.warning("Champions: Claude returned insufficient results: %s", champions)
        return

    run_at = datetime.utcnow()

    # Only wipe old data after Claude succeeds
    db.query(Champion).delete()
    for strategy, data in champions.items():
        if not data or not data.get("ticker"):
            continue
        db.add(Champion(
            strategy=strategy,
            ticker=data["ticker"],
            score=data.get("score"),
            grade=data.get("grade"),
            reason=data.get("reason"),
            universe_size=len(UNIVERSE),
            survivors_count=len(survivors),
            run_at=run_at,
        ))
    db.commit()
    logger.info("Champions saved: %s", {s: d.get("ticker") for s, d in champions.items()})
