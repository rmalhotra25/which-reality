"""
IV snapshot service.

On each scheduler run, snap the ATM IV for every ticker in the app's
universe and store one row in iv_snapshots.  Percentile queries over
that history let the UI and later phases know where current IV sits
relative to the past.

Snap priority:
  1. Polygon live options snapshot (requires POLYGON_API_KEY)
  2. yfinance options chain
  3. Historical volatility as a labeled fallback
If nothing works for a ticker, nothing is stored and a skip is logged.
"""
import logging
import math
from datetime import datetime, timezone, date

logger = logging.getLogger(__name__)

# Combined wheel + directional universe
def _universe() -> list[str]:
    from services.stock_data import DEFAULT_UNIVERSE
    return list(DEFAULT_UNIVERSE)


def snap_iv_universe(db) -> dict:
    """
    Snap ATM IV for every ticker in the universe.
    Returns {"stored": int, "skipped": int, "tickers": list}.
    Safe to call from a background thread -- opens its own mini-session
    context via the passed db session.
    """
    tickers = _universe()
    stored = 0
    skipped = []

    for ticker in tickers:
        try:
            row = _snap_one(ticker)
            if row is None:
                skipped.append(ticker)
                continue
            from models.iv_snapshot import IVSnapshot
            snap = IVSnapshot(
                ticker=ticker,
                captured_at=datetime.now(timezone.utc),
                atm_iv=row["atm_iv"],
                underlying_price=row["underlying_price"],
                expiry=row.get("expiry"),
                dte=row.get("dte"),
                iv_source=row["iv_source"],
            )
            db.add(snap)
            stored += 1
        except Exception as e:
            logger.warning("iv_snapshot: skip %s: %s", ticker, e)
            skipped.append(ticker)

    try:
        db.commit()
    except Exception as e:
        logger.error("iv_snapshot: commit failed: %s", e)
        db.rollback()
        return {"stored": 0, "skipped": tickers}

    logger.info("iv_snapshot: stored=%d skipped=%d", stored, len(skipped))
    if skipped:
        logger.info("iv_snapshot: skipped tickers: %s", skipped[:20])
    return {"stored": stored, "skipped": len(skipped), "tickers_stored": stored}


def _snap_one(ticker: str) -> dict | None:
    """
    Fetch ATM IV for a single ticker.
    Returns {"atm_iv", "underlying_price", "expiry", "dte", "iv_source"}
    or None if no data is available.
    """
    # --- Polygon live options snapshot ---
    try:
        from config import settings
        if settings.polygon_api_key:
            from services.polygon_client import get_ticker_snapshot, get_options_chain_snapshot
            snap = get_ticker_snapshot(ticker)
            price = snap.get("price") or snap.get("prev_close") or 0
            if price > 0:
                snaps = get_options_chain_snapshot(
                    ticker, dte_max=45, near_price=price, strike_pct_range=0.05
                )
                today = date.today()
                best_iv = None
                best_dte = None
                best_expiry = None
                for s in (snaps or []):
                    if not s.details:
                        continue
                    if (s.details.contract_type or "").lower() != "call":
                        continue
                    if not s.implied_volatility:
                        continue
                    try:
                        exp = str(s.details.expiration_date)
                        dte = (date.fromisoformat(exp) - today).days
                        if dte < 7 or dte > 45:
                            continue
                        diff = abs(float(s.details.strike_price or 0) - price)
                        if best_iv is None or diff < abs(float(s.details.strike_price or 0) - price):
                            best_iv = float(s.implied_volatility)
                            best_dte = dte
                            best_expiry = exp
                    except Exception:
                        continue
                if best_iv is not None and best_iv > 0:
                    return {
                        "atm_iv": best_iv,
                        "underlying_price": float(price),
                        "expiry": best_expiry,
                        "dte": best_dte,
                        "iv_source": "polygon",
                    }
    except Exception as e:
        logger.debug("iv_snap Polygon failed for %s: %s", ticker, e)

    # --- yfinance options chain ---
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expiries = t.options
        today = date.today()
        target_expiry = None
        for exp in (expiries or []):
            dte = (date.fromisoformat(exp) - today).days
            if 14 <= dte <= 45:
                target_expiry = exp
                break
        if target_expiry:
            price = float(t.fast_info.last_price or t.fast_info.previous_close or 0)
            if price > 0:
                chain = t.option_chain(target_expiry)
                calls = chain.calls
                if not calls.empty:
                    atm_idx = (calls["strike"] - price).abs().idxmin()
                    atm_iv = float(calls.loc[atm_idx, "impliedVolatility"])
                    if atm_iv > 0:
                        dte = (date.fromisoformat(target_expiry) - today).days
                        return {
                            "atm_iv": atm_iv,
                            "underlying_price": price,
                            "expiry": target_expiry,
                            "dte": dte,
                            "iv_source": "yfinance",
                        }
    except Exception as e:
        logger.debug("iv_snap yfinance failed for %s: %s", ticker, e)

    # --- HV fallback (no options data available) ---
    try:
        from services.stock_data import _historical_volatility, _yf_fetch_ohlcv
        hv = _historical_volatility(ticker, days=30)
        if hv and hv > 0:
            # Get a price too
            df = _yf_fetch_ohlcv(ticker, period_days=5)
            price = float(df["Close"].iloc[-1]) if not df.empty else None
            if price:
                return {
                    "atm_iv": hv,
                    "underlying_price": price,
                    "expiry": None,
                    "dte": None,
                    "iv_source": "hv_fallback",
                }
    except Exception as e:
        logger.debug("iv_snap HV fallback failed for %s: %s", ticker, e)

    return None


def get_iv_percentile(db, ticker: str) -> dict:
    """
    Return the percentile of the latest stored IV within this ticker's own history.

    When fewer than 30 snapshots exist the flag history_building=True is set
    so callers can label the result as approximate.
    """
    from models.iv_snapshot import IVSnapshot
    from sqlalchemy import asc

    rows = (
        db.query(IVSnapshot)
        .filter(IVSnapshot.ticker == ticker.upper())
        .order_by(asc(IVSnapshot.captured_at))
        .all()
    )
    n = len(rows)
    if n == 0:
        return {
            "ticker": ticker.upper(),
            "available": False,
            "reason": "no snapshots stored yet",
        }

    latest = rows[-1]
    current_iv = latest.atm_iv
    history_ivs = [r.atm_iv for r in rows]

    # Percentile: fraction of stored values below current
    below = sum(1 for v in history_ivs if v < current_iv)
    percentile = round(below / n * 100, 1)

    return {
        "ticker": ticker.upper(),
        "available": True,
        "iv_percentile": percentile,
        "atm_iv_pct": round(current_iv * 100, 1),
        "sample_count": n,
        "history_building": n < 30,
        "iv_source": latest.iv_source,
        "captured_at": latest.captured_at.isoformat(),
    }
