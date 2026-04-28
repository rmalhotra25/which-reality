"""
Champions Engine — daily market-open scan.

1. Pre-screens ~50 curated stocks with Python (free, fast).
2. Passes survivors to Claude in ONE batched call.
3. Stores three champion records (wheel / options / longterm) in the DB.
"""
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stock universe (~50 curated names across sectors and strategies)
# ---------------------------------------------------------------------------
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

MIN_AVG_VOLUME = 500_000
MIN_PRICE = 5.0
RSI_LOW, RSI_HIGH = 25.0, 75.0
EARNINGS_BUFFER_DAYS = 14


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    try:
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi_series = 100 - (100 / (1 + rs))
        val = rsi_series.iloc[-1]
        return round(float(val), 1) if pd.notna(val) else None
    except Exception:
        return None


def _earnings_days_away(ticker: str) -> int | None:
    """Return days until next earnings, or None if unknown."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return None
        ed_col = cal.get("Earnings Date")
        if ed_col is None or len(ed_col) == 0:
            return None
        ed = ed_col[0]
        # ed may be a Timestamp
        ed_date = pd.Timestamp(ed).date()
        today = datetime.now(timezone.utc).date()
        return (ed_date - today).days
    except Exception:
        return None


def prescreen() -> list[dict]:
    """
    Download bulk price/volume history for the universe, compute RSI,
    filter by basic criteria, and return survivors as dicts.
    """
    logger.info("Champions: downloading bulk data for %d tickers", len(UNIVERSE))
    try:
        raw = yf.download(
            UNIVERSE,
            period="3mo",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception as e:
        logger.error("Champions bulk download failed: %s", e)
        return []

    survivors = []
    today = datetime.now(timezone.utc).date()

    for ticker in UNIVERSE:
        try:
            # Handle both single-ticker and multi-ticker DataFrame structures
            if len(UNIVERSE) == 1:
                df = raw
            else:
                if ticker not in raw.columns.get_level_values(0):
                    continue
                df = raw[ticker].dropna(how="all")

            if df.empty or len(df) < 20:
                continue

            price = float(df["Close"].iloc[-1])
            avg_vol = float(df["Volume"].tail(20).mean())

            if price < MIN_PRICE:
                continue
            if avg_vol < MIN_AVG_VOLUME:
                continue

            rsi = _rsi(df["Close"])
            if rsi is not None and (rsi < RSI_LOW or rsi > RSI_HIGH):
                continue

            # Quick earnings check (only for survivors so far — keeps it fast)
            days_to_earnings = _earnings_days_away(ticker)
            if days_to_earnings is not None and 0 <= days_to_earnings <= EARNINGS_BUFFER_DAYS:
                logger.debug("Champions: skipping %s — earnings in %d days", ticker, days_to_earnings)
                continue

            # Approximate IV rank from options chain ATM IV (best effort)
            iv_rank = None
            try:
                t = yf.Ticker(ticker)
                expiries = t.options
                if expiries:
                    chain = t.option_chain(expiries[0])
                    puts = chain.puts
                    if not puts.empty:
                        atm_idx = (puts["strike"] - price).abs().idxmin()
                        iv = float(puts.loc[atm_idx, "impliedVolatility"]) * 100
                        iv_rank = round(min(iv / 0.5, 100), 1)
            except Exception:
                pass

            # Basic fundamentals
            info = {}
            try:
                info = yf.Ticker(ticker).info or {}
            except Exception:
                pass

            survivors.append({
                "ticker": ticker,
                "price": round(price, 2),
                "avg_vol_m": round(avg_vol / 1_000_000, 1),
                "rsi": rsi,
                "iv_rank": iv_rank,
                "pe": info.get("trailingPE"),
                "div_yield_pct": round(info.get("dividendYield", 0) * 100, 2) if info.get("dividendYield") else None,
                "sector": info.get("sector", ""),
                "analyst": info.get("recommendationKey", ""),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
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
        logger.warning("Champions: not enough survivors (%d) to pick champions", len(survivors))
        return

    analyst = ClaudeAnalyst()
    try:
        champions = analyst.pick_champions(survivors)
    except Exception as e:
        logger.error("Champions Claude call failed: %s", e, exc_info=True)
        return

    run_at = datetime.utcnow()

    # Delete old champions and insert fresh ones
    db.query(Champion).delete()
    for strategy, data in champions.items():
        if not data.get("ticker"):
            continue
        row = Champion(
            strategy=strategy,
            ticker=data["ticker"],
            score=data.get("score"),
            grade=data.get("grade"),
            reason=data.get("reason"),
            universe_size=len(UNIVERSE),
            survivors_count=len(survivors),
            run_at=run_at,
        )
        db.add(row)
    db.commit()
    logger.info("Champions saved: %s", {s: d.get("ticker") for s, d in champions.items()})
