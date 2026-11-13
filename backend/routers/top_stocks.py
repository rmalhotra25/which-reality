"""Top stocks router: GET /api/top-stocks.

The five best purchase candidates from the quality-screener
universe, grade A first then B, Buy Big before Buy Small before
Hold. A fetch failure is reported as unavailable, never invented.
"""

import logging

from fastapi import APIRouter

from services import top_stocks as top_stocks_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/top-stocks", tags=["TopStocks"])


@router.get("")
def get_top_stocks():
    return top_stocks_service.build_top_stocks()
