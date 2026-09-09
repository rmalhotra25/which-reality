import logging
import threading
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leveraged-ma", tags=["Leveraged MA"])

_daily_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


@router.get("/signals")
def get_signals():
    """Current MA signal state + live intraday prices for all active asset configs."""
    from services.leveraged_ma_service import get_signals_dashboard
    return get_signals_dashboard()


@router.get("/backtest")
def backtest(
    asset_key: str,
    direction: str = "trend_follow",
    ma_period: int = 200,
    threshold_pct: float = 0.0,
):
    """Run historical backtest for a given asset/direction/params."""
    from services.leveraged_ma_service import run_backtest
    try:
        return run_backtest(asset_key, direction, ma_period, threshold_pct)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/run-daily")
def trigger_daily():
    """Force-trigger the daily signal engine (normally runs after market close)."""
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
    """Return the list of active asset configs."""
    from services.leveraged_ma_service import ASSET_CONFIGS
    return [c for c in ASSET_CONFIGS if c["active"]]
