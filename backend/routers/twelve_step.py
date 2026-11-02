from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/twelve-step", tags=["12 Step"])


class ScreenerFilters(BaseModel):
    # Nash Step 3 pre-screen defaults. Every threshold is user-adjustable.
    # Percentages here are percent values, for example 10.0 means 10 percent.
    market_cap_min: int = 1_000_000_000
    market_cap_max: int | None = None
    sector: str | None = None
    min_volume: int = 200_000
    country: str = "US"
    limit: int = 100
    fcf_positive: bool = True
    net_cash_positive: bool = True
    revenue_growth_min: float = 10.0
    short_interest_max: float = 10.0
    operating_margin_min: float = 20.0
    earnings_misses_max: int = 1
    exclude_china: bool = True
    exclude_airlines: bool = True
    exclude_commodities: bool = True


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
        return {"status": "no_key", "results": [], "filters_omitted": ["all"]}
    from services.fmp_client import run_screener as _screen
    try:
        payload = _screen(
            market_cap_min=filters.market_cap_min,
            market_cap_max=filters.market_cap_max,
            sector=filters.sector,
            min_volume=filters.min_volume,
            country=filters.country,
            limit=filters.limit,
            fcf_positive=filters.fcf_positive,
            net_cash_positive=filters.net_cash_positive,
            revenue_growth_min=filters.revenue_growth_min,
            short_interest_max=filters.short_interest_max,
            operating_margin_min=filters.operating_margin_min,
            exclude_china=filters.exclude_china,
            exclude_airlines=filters.exclude_airlines,
            exclude_commodities=filters.exclude_commodities,
        )
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
