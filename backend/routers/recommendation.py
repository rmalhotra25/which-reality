"""Answer block router: GET /api/recommendation/{ticker}.

One recommendation for one ticker, in plain words: Buy Big, Buy
Small, Hold, or Sell, with the evidence behind it. The
recommendation comes from the recommendation service, which
combines the Story, the trend, news catalysts, the roadmap, and
insider activity under explicit rules. A fetch failure is
reported as unavailable, never invented.
"""

import logging

from fastapi import APIRouter

from services import recommendation as recommendation_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommendation", tags=["Answer"])


@router.get("/{ticker}")
def get_recommendation(ticker: str):
    return recommendation_service.build_recommendation(ticker)
