"""Company search router: GET /api/search?q=<query>.

Returns matching tickers for a company name or a partial ticker.
A source failure returns an empty list with status ok, never a 500.
"""

import logging

from fastapi import APIRouter, Query

from services import search as search_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["Search"])


@router.get("")
def search_companies(q: str = Query(default="")):
    return {
        "status": "ok",
        "query": q,
        "results": search_service.search_companies(q),
    }
