from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/twelve-step", tags=["12 Step"])


class ScreenerFilters(BaseModel):
    market_cap_min: int = 1_000_000_000
    market_cap_max: int | None = None
    sector: str | None = None
    min_volume: int = 200_000
    country: str = "US"
    limit: int = 40


@router.get("/data/{ticker}")
def get_ticker_data(ticker: str):
    from services.twelve_step_service import get_twelve_step_data
    try:
        data = get_twelve_step_data(ticker.upper())
        if not data.get("company_name") and not data.get("current_price"):
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screener")
def run_screener(filters: ScreenerFilters):
    from config import settings
    if not settings.fmp_api_key:
        return {"status": "no_key", "results": []}
    from services.fmp_client import run_screener as _screen
    try:
        results = _screen(
            market_cap_min=filters.market_cap_min,
            market_cap_max=filters.market_cap_max,
            sector=filters.sector,
            min_volume=filters.min_volume,
            country=filters.country,
            limit=filters.limit,
        )
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
