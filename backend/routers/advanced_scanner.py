from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/advanced-scanner", tags=["Advanced Scanner"])


@router.get("/status/{scan_type}")
def scan_status(scan_type: str):
    if scan_type not in ("dividend", "movers"):
        raise HTTPException(status_code=400, detail="scan_type must be 'dividend' or 'movers'")
    from services.advanced_scanner_service import get_scan_status, _cache_timestamp
    status = get_scan_status(scan_type)
    status["last_cached_at"] = _cache_timestamp(scan_type)
    return status


@router.get("/dividend")
def get_dividend_results():
    """Return cached dividend scan results. Use POST /refresh/dividend to start a scan."""
    from services.advanced_scanner_service import _load_cache
    cached = _load_cache("dividend")
    if cached:
        return cached
    return {"results": [], "scanning": False, "mode": "dividend",
            "message": "No cached results yet. POST /api/advanced-scanner/refresh/dividend to start a scan."}


@router.get("/movers")
def get_mover_results():
    """Return cached big mover scan results. Use POST /refresh/movers to start a scan."""
    from services.advanced_scanner_service import _load_cache
    cached = _load_cache("movers")
    if cached:
        return cached
    return {"results": [], "scanning": False, "mode": "movers",
            "message": "No cached results yet. POST /api/advanced-scanner/refresh/movers to start a scan."}


@router.post("/refresh/{scan_type}")
def refresh_scan(scan_type: str):
    """Force a fresh scan, ignoring cache."""
    if scan_type not in ("dividend", "movers"):
        raise HTTPException(status_code=400, detail="scan_type must be 'dividend' or 'movers'")
    from services.advanced_scanner_service import launch_scan_background, get_scan_status
    status = get_scan_status(scan_type)
    if status["running"]:
        return {"status": "already_running", "message": f"{scan_type} scan is already in progress"}
    launch_scan_background(scan_type)
    return {"status": "started", "message": f"{scan_type} scan launched in background"}


@router.get("/debug/{ticker}")
def debug_fundamentals(ticker: str):
    """Return raw Finnhub metrics for a ticker — used to diagnose pre-filter issues."""
    from services.finnhub_client import get_basic_financials
    metrics = get_basic_financials(ticker.upper())
    # Return the fields relevant to scanner pre-filters
    fields = [
        "dividendYieldIndicatedAnnual", "currentDividendYieldTTM", "dividendYield5Y",
        "dividendPerShareAnnual", "dividendPerShareTTM",
        "payoutRatioTTM",
        "revenueGrowthTTMYoy", "revenueGrowth3M",
        "grossMarginTTM", "marketCapitalization",
        "10DayAverageTradingVolumeMillion", "3MonthAverageTradingVolumeMillion",
        "psTTM", "52WeekHigh", "beta",
    ]
    return {
        "ticker": ticker.upper(),
        "raw_metrics": {k: metrics.get(k) for k in fields},
        "all_keys_count": len(metrics),
    }
