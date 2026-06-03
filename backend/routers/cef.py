import threading
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/cef", tags=["CEF Scanner"])

_scan_thread: threading.Thread | None = None


@router.get("/scan")
def get_scan(force: bool = False):
    from services.cef_service import scan_universe
    return scan_universe(force=force)


@router.post("/refresh")
def refresh_scan():
    global _scan_thread
    if _scan_thread and _scan_thread.is_alive():
        return {"status": "already_running"}
    from services.cef_service import scan_universe
    _scan_thread = threading.Thread(
        target=scan_universe, kwargs={"force": True}, daemon=True, name="cef-scanner"
    )
    _scan_thread.start()
    return {"status": "started"}


@router.get("/analyze/{ticker}")
def analyze_ticker(ticker: str):
    from services.cef_service import analyze_cef
    try:
        return analyze_cef(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/universe")
def get_universe():
    from services.cef_service import _CEF_UNIVERSE
    return {"tickers": _CEF_UNIVERSE, "count": len(_CEF_UNIVERSE)}
