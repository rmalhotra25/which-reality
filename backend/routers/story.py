"""Company Story router: GET /api/story/{ticker}.

A read-only explainer for one ticker, shown inside the ticker lookup.
Never a trade call, never LIVE, no sizing. All numbers come from the
story service; a fetch failure is reported as unavailable, never
invented.
"""

import logging

from fastapi import APIRouter

from services import story as story_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/story", tags=["Story"])


@router.get("/{ticker}")
def get_story(ticker: str):
    return story_service.build_story(ticker)
