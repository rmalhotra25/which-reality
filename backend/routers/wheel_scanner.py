"""
Wheel scanner router.

GET  /api/wheel/scanner/candidates -- returns cached results only (never triggers a scan)
GET  /api/wheel/scanner/calls      -- cached covered-call results only
GET  /api/wheel/scanner/status     -- run_status entry for wheel_scanner
POST /api/wheel/scanner/refresh    -- triggers a full put + call scan in the background
"""
import logging
import threading

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
import services.run_status as run_status

router = APIRouter(prefix="/api/wheel/scanner", tags=["Wheel Scanner"])
logger = logging.getLogger(__name__)


@router.get("/candidates")
def get_scanner_candidates():
    """Return the cached put-scanner results. Never triggers a scan."""
    from services.wheel_scanner_service import get_put_cache
    cache = get_put_cache()
    if cache is None:
        return {"cached": False, "message": "No scan has run yet. POST /refresh to start one."}
    return {**cache, "cached": True}


@router.get("/calls")
def get_scanner_calls():
    """Return the cached covered-call scanner results. Never triggers a scan."""
    from services.wheel_scanner_service import get_call_cache
    cache = get_call_cache()
    if cache is None:
        return {"cached": False, "message": "No scan has run yet. POST /refresh to start one."}
    return {**cache, "cached": True}


@router.get("/status")
def get_scanner_status():
    """Return run_status entry for the wheel scanner."""
    all_status = run_status.get_all()
    return all_status.get("wheel_scanner", {"state": "idle"})


@router.post("/refresh")
def trigger_scanner_refresh(db: Session = Depends(get_db)):
    """Trigger a full put + call scan in a background thread. Returns immediately."""
    current = run_status.get_all().get("wheel_scanner", {})
    if current.get("state") == "running":
        return {"started": False, "message": "Scan already in progress."}

    def _run():
        from database import SessionLocal
        _db = SessionLocal()
        try:
            from services.wheel_scanner_service import run_put_scanner, run_call_scanner
            run_put_scanner(_db)
            run_call_scanner(_db)
        except Exception as e:
            run_status.set_error("wheel_scanner", str(e))
            logger.error("wheel_scanner refresh failed: %s", e, exc_info=True)
        finally:
            _db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "message": "Wheel scanner started in background."}
