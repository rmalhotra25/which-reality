import logging
import threading
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leveraged-ma", tags=["Leveraged MA"])

_daily_thread: threading.Thread | None = None
_daily_error: str | None = None
_thread_lock = threading.Lock()


@router.get("/signals")
def get_signals():
    """Current confirmed-position state + live intraday prices for all active pairs."""
    from services.leveraged_ma_service import get_signals_dashboard
    return get_signals_dashboard()


@router.get("/cash-apy")
def get_cash_apy():
    """Fetch current recommended cash APY using SGOV/BIL dividend yield from Finnhub."""
    from services.leveraged_ma_service import get_current_cash_apy
    return get_current_cash_apy()


@router.get("/backtest")
def backtest(
    asset_key: str,
    ma_period: int = 161,
    entry_buffer_pct: float = 1.0,
    exit_buffer_pct: float = -2.5,
    cash_apy_pct: float = 4.5,
):
    """
    Run historical backtest for a given asset pair and parameters.
    Returns full-period stats, sub-period breakdowns, and chart data arrays.
    """
    from services.leveraged_ma_service import run_backtest
    try:
        return run_backtest(asset_key, ma_period, entry_buffer_pct, exit_buffer_pct, cash_apy_pct)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _engine_thread():
    global _daily_error
    from services.leveraged_ma_service import run_daily_signal_engine
    try:
        run_daily_signal_engine()
        _daily_error = None
    except Exception as e:
        logger.error("run-daily thread: engine error: %s", e, exc_info=True)
        _daily_error = str(e)


@router.post("/run-daily")
def trigger_daily():
    """Force-trigger the daily signal engine (normally runs Mon–Fri at 17:00 ET)."""
    global _daily_thread
    with _thread_lock:
        if _daily_thread and _daily_thread.is_alive():
            return {"status": "already_running", "error": None}
        _daily_thread = threading.Thread(target=_engine_thread, daemon=True)
        _daily_thread.start()
    return {"status": "started", "error": None}


@router.get("/run-daily/status")
def daily_status():
    """Poll whether the last run-daily invocation is still running or finished."""
    with _thread_lock:
        running = bool(_daily_thread and _daily_thread.is_alive())
    return {"running": running, "error": _daily_error}


@router.get("/health")
def health():
    """Diagnostic: check API keys, DB rows, and a live Polygon price fetch."""
    import os
    from config import settings

    result = {
        "polygon_key_set": bool(os.environ.get("POLYGON_API_KEY") or settings.polygon_api_key),
        "finnhub_key_set": bool(os.environ.get("FINNHUB_API_KEY") or getattr(settings, "finnhub_api_key", None)),
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
        "db_rows": None,
        "polygon_test": None,
        "last_engine_error": _daily_error,
    }

    # Count DB rows
    try:
        from database import SessionLocal
        from models.leveraged_ma import LeveragedMASignalState
        db = SessionLocal()
        result["db_rows"] = db.query(LeveragedMASignalState).count()
        db.close()
    except Exception as e:
        result["db_rows"] = f"ERROR: {e}"

    # Test Polygon with full 171-day fetch for each underlying (same as engine)
    try:
        from services.polygon_client import get_close_prices
        from services.leveraged_ma_service import ASSET_CONFIGS
        underlyings = list({cfg["underlying"] for cfg in ASSET_CONFIGS if cfg["active"]})
        poly_results = {}
        for ticker in underlyings:
            try:
                closes = get_close_prices(ticker, days=171)
                poly_results[ticker] = f"{len(closes)} closes (need 161+)"
            except Exception as e:
                poly_results[ticker] = f"ERROR: {e}"
        result["polygon_test"] = poly_results
    except Exception as e:
        result["polygon_test"] = f"ERROR: {e}"

    return result


@router.get("/configs")
def get_configs():
    """Return the list of active asset configs with strategy parameters."""
    from services.leveraged_ma_service import ASSET_CONFIGS, CONFIRMATION_DAYS, ENTRY_BUFFER_PCT, EXIT_BUFFER_PCT
    return {
        "confirmation_days": CONFIRMATION_DAYS,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "pairs": [c for c in ASSET_CONFIGS if c["active"]],
    }
