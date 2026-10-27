import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/dividend-path", tags=["Dividend Income Path"])

_scan_thread: threading.Thread | None = None


def _scan_running_response() -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={
            "status": "scan_running",
            "detail": "Dividend scan is running in the background. Try again shortly.",
        },
    )


def _start_scan(starting_capital: float, weekly_dca: float) -> None:
    global _scan_thread
    if _scan_thread and _scan_thread.is_alive():
        return
    from services.dividend_path_service import build_dividend_path

    _scan_thread = threading.Thread(
        target=build_dividend_path,
        kwargs={
            "starting_capital": starting_capital,
            "weekly_dca": weekly_dca,
            "force": True,
        },
        daemon=True,
        name="dividend-path-scanner",
    )
    _scan_thread.start()


@router.get("/recommend")
def get_recommendation(
    starting_capital: float = 61000.0,
    weekly_dca: float = 500.0,
    force: bool = False,
):
    """Return the cached dividend path, or 202 while a background scan runs.

    A cold cache used to block the Income tab for a full live scan (dozens
    of tickers through yfinance, over 25 seconds). Now a cold cache starts
    the scan in the background and returns 202 immediately, so the tab
    never hangs waiting for it.
    """
    from services.dividend_path_service import build_dividend_path, peek_cached

    if not force:
        cached = peek_cached(starting_capital, weekly_dca)
        if cached:
            return cached
        _start_scan(starting_capital, weekly_dca)
        return _scan_running_response()
    try:
        return build_dividend_path(starting_capital=starting_capital, weekly_dca=weekly_dca, force=force)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/project")
def project(
    starting_capital: float = 61000.0,
    monthly_contribution: float = 500.0,
):
    """Re-project the cached portfolio for a new monthly contribution.

    No rescan: it reuses the cached portfolio and the backend projection
    model (_build_projection) with the same base and bear assumptions, so
    the Income tab slider answers instantly. Monthly contribution is
    clamped to $100-$2,000. Returns 202 while a scan runs if no cached
    portfolio exists yet.
    """
    from services.dividend_path_service import project_from_cached

    monthly = max(100.0, min(float(monthly_contribution), 2000.0))
    result = project_from_cached(starting_capital, monthly)
    if result is not None:
        return result
    _start_scan(starting_capital, monthly * 12 / 52)
    return _scan_running_response()


@router.post("/refresh")
def refresh(starting_capital: float = 61000.0, weekly_dca: float = 500.0):
    global _scan_thread
    if _scan_thread and _scan_thread.is_alive():
        return {"status": "already_running"}
    from services.dividend_path_service import build_dividend_path

    _scan_thread = threading.Thread(
        target=build_dividend_path,
        kwargs={"starting_capital": starting_capital, "weekly_dca": weekly_dca, "force": True},
        daemon=True,
        name="dividend-path-scanner",
    )
    _scan_thread.start()
    return {"status": "started"}


class CustomHolding(BaseModel):
    ticker: str
    dollar_amount: float
    dca_pct: float


class CustomPortfolioRequest(BaseModel):
    holdings: list[CustomHolding]
    starting_capital: float = 61000.0
    weekly_dca: float = 500.0


@router.post("/run-custom")
def run_custom(req: CustomPortfolioRequest):
    from services.dividend_path_service import run_custom_portfolio

    try:
        return run_custom_portfolio(
            holdings=[h.model_dump() for h in req.holdings],
            starting_capital=req.starting_capital,
            weekly_dca=req.weekly_dca,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


class LumpSumRequest(BaseModel):
    lump_amount: float
    starting_capital: float = 61000.0
    weekly_dca: float = 500.0


@router.post("/lump-sum")
def lump_sum_allocation(req: LumpSumRequest):
    from services.dividend_path_service import build_dividend_path, _distribute_lump_sum

    try:
        data = build_dividend_path(starting_capital=req.starting_capital, weekly_dca=req.weekly_dca)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    portfolio = data["portfolio"]
    allocation = _distribute_lump_sum(portfolio, req.lump_amount)
    total_added_income = sum(a["added_monthly_income"] for a in allocation)
    return {
        "lump_amount": req.lump_amount,
        "allocation": allocation,
        "total_added_monthly_income": round(total_added_income, 2),
        "total_added_annual_income": round(total_added_income * 12, 2),
    }
