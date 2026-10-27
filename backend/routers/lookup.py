"""
Ticker lookup router (deterministic query).

GET /api/lookup/{ticker} -- snapshot for one ticker, from the same
rule registry check the alert engine runs, on demand.

Read-only: no alert is fired, no journal row is created, no Telegram
message is sent, no run receipt is written. This router imports none
of those writers.

Claude explains only, and only when ?explain=true is passed: the
quant result is computed first, and a Claude failure leaves it
untouched with the quant fallback text in place.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db
from services.ticker_lookup import LookupError, lookup_ticker

router = APIRouter(prefix="/api/lookup", tags=["Ticker Lookup"])


def _claude_explain_fn(ticker: str):
    """Adapt ClaudeAnalyst.explain_watchlist to the explain_fn shape
    ai_boundary.explain_or_fallback expects: a callable taking a list
    of candidate dicts and returning a list of {ticker, explanation}."""
    def _explain(candidates):
        from services.claude_analyst import ClaudeAnalyst

        quant = {}
        for cand in candidates or []:
            quant["quant_score"] = cand.get("quant_score")
            quant["strategy"] = cand.get("strategy")
        notes = ClaudeAnalyst().explain_watchlist(ticker, quant) or {}
        text = (notes.get("summary") or notes.get("options_note") or "").strip()
        if not text:
            return []
        return [{"ticker": ticker, "explanation": text}]

    return _explain


@router.get("/{ticker}")
def get_lookup(ticker: str, explain: bool = Query(False), db=Depends(get_db)):
    try:
        return lookup_ticker(
            ticker, db=db,
            explain_fn=_claude_explain_fn(ticker.upper().strip()) if explain else None,
        )
    except LookupError as e:
        status = 404 if e.code in ("invalid_ticker", "unknown_ticker", "no_data", "no_indicators") else 502
        raise HTTPException(status_code=status, detail={"error": e.code, "reason": e.reason})
