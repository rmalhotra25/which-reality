import logging
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/flow", tags=["Options Flow"])
logger = logging.getLogger(__name__)


@router.get("/scan")
def scan_options_flow():
    """Scan options chains for unusual volume vs open interest and return AI-interpreted alerts."""
    try:
        from services.options_flow_engine import run_flow_scan
        result = run_flow_scan()
        if result.get("error") and not result.get("alerts"):
            raise HTTPException(status_code=503, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Options flow scan failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Flow scan failed: {str(e)}")
