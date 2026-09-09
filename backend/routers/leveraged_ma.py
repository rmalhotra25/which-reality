import logging
import threading
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leveraged-ma", tags=["Leveraged MA"])

_daily_thread: threading.Thread | None = None
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


@router.post("/run-daily")
def trigger_daily():
    """Force-trigger the daily signal engine (normally runs Mon–Fri at 17:00 ET)."""
    global _daily_thread
    with _thread_lock:
        if _daily_thread and _daily_thread.is_alive():
            return {"status": "already_running"}
        from services.leveraged_ma_service import run_daily_signal_engine
        _daily_thread = threading.Thread(target=run_daily_signal_engine, daemon=True)
        _daily_thread.start()
    return {"status": "started"}


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
