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

A lookup never answers with a bare 500: a known data failure is a
named LookupError, and anything unexpected is logged and returned as
a named lookup_failed 502, so the tab can show the reason plainly.
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db
from services.ticker_lookup import LookupError, lookup_ticker

logger = logging.getLogger(__name__)

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


def _build_ondemand(ticker: str, db):
    """On-demand review, read-only, graceful on live fetch failure.

    Calls the existing lookup first for price, trend, timing
    verdict, earnings, and SPY gate, then adds live quality,
    live statements, a live long-term lane, a DCA decision,
    and evidence-based AI proposals. If a live fetch fails,
    the review still returns, with quality not_verified and
    a cannot_judge DCA decision, never a bare 500.
    """
    from services.longterm_valuation import build_longterm
    from services.ondemand_review import (
        build_ondemand_review, build_proposals, fetch_live_quality_inputs,
        fetch_statements, score_live_quality,
    )
    from services.finnhub_client import get_company_profile

    base = lookup_ticker(ticker, db=db)
    ticker = base.get("ticker") or ticker.upper().strip()
    price = base.get("price")
    trend = base.get("trend") or {}
    verdict = base.get("verdict") or {}
    stock = verdict.get("stock") or {}
    earnings_raw = base.get("earnings") or {}
    earnings = {
        "days_away": earnings_raw.get("earnings_days"),
        "status": earnings_raw.get("status"),
    }
    try:
        quality_live = score_live_quality(fetch_live_quality_inputs(ticker))
    except Exception as exc:
        logger.warning("on-demand live quality failed for %s: %s", ticker, exc)
        quality_live = {
            "status": "not_verified", "run_date": None,
            "source": "live_on_demand", "composite": None,
            "label": None, "missing": ["live_quality_fetch"],
            "kills": {}, "note": f"Live quality fetch failed: {exc}.",
        }
    try:
        profile = get_company_profile(ticker) or {}
    except Exception:
        profile = {}
    statements, statements_note = fetch_statements(ticker, price)
    if statements is not None:
        statements["revenue_growth_pct"] = quality_live.get("rev_cagr_3y_pct")
        statements["operating_margin_pct"] = quality_live.get("operating_margin_pct")
        statements["ev_to_ebitda"] = quality_live.get("ev_to_ebitda")
        # Multi-year history for the normalized DCF, only on the
        # yfinance fallback path, where annuals are already wired.
        # Polygon SEC path supplies no history, so normalized falls
        # back to the verified 3-year average margin there.
        if statements.get("statements_source") == "yfinance_annual":
            try:
                from services.twelve_step_service import _get_annual_financials_list

                annuals = _get_annual_financials_list(ticker, 3) or []
                history = []
                for row in annuals:
                    try:
                        history.append({
                            "revenue": float(row.get("revenue")) / 1_000_000.0,
                            "fcf": float(row.get("free_cash_flow")) / 1_000_000.0,
                        })
                    except (TypeError, ValueError):
                        continue
                if history:
                    statements["history"] = history
            except Exception:
                pass
    live_yield = None
    try:
        from services.dcf_methods import fetch_live_10y_yield

        live_yield = fetch_live_10y_yield()
    except Exception:
        live_yield = None
    try:
        longterm_live = build_longterm(
            ticker, price, quality_live, statements=statements,
            risk_free_rate=live_yield)
        # build_longterm rebuilds quality from the snapshot shape,
        # which drops the live kills and missing list. Put the
        # full live quality back, so the frontend can show them.
        longterm_live["quality"] = quality_live
        if statements is None:
            longterm_live["statements_note"] = statements_note
    except Exception as exc:
        logger.warning("on-demand long-term failed for %s: %s", ticker, exc)
        longterm_live = {
            "verdict": "not_verified", "label": "NOT VERIFIED",
            "reason": f"Long-term lane failed: {exc}.",
            "reason_code": "not_verified", "quality": quality_live,
            "dcf": None, "wacc": None, "bridge_line": None,
            "bridge_entry": None, "dcf_methods": None, "notes": [],
        }
    try:
        tenure = {}
        market = {}
        proposals = build_proposals(quality_live, profile, tenure, market)
    except Exception as exc:
        logger.warning("on-demand proposals failed for %s: %s", ticker, exc)
        proposals = {}
    review = build_ondemand_review(
        ticker, price, trend, stock, base.get("setups") or [],
        base.get("spy_gate") or {}, earnings, quality_live,
        longterm_live, proposals,
    )
    # Options Strategies for the on-demand section, from the same
    # listed chain the snapshot lookup already fetched. Additional
    # information only, never a verdict driver.
    try:
        from services.option_strategies import build_option_strategies

        chain = base.get("chain") or {}
        review["option_strategies"] = build_option_strategies(
            price, chain.get("puts") or [], chain.get("calls") or [],
            chain_source=chain.get("source"), chain_error=chain.get("error"))
    except Exception as exc:
        logger.warning("on-demand option strategies failed for %s: %s", ticker, exc)
        review["option_strategies"] = {
            "available": False, "expiry": None, "dte": None,
            "expiry_rule": None, "chain_source": None,
            "selection_note": None, "best_call": None, "best_put": None,
            "straddle": None, "iron_condor": None,
            "reason": f"Option strategies could not be computed: {exc}.",
        }
    review["snapshot"] = {
        "longterm": verdict.get("longterm"),
        "dca": verdict.get("dca"),
        "timing_decision": stock.get("decision"),
        "note": (
            "Snapshot lane, unchanged, shown for comparison. "
            "The live review above does not overwrite it."
        ),
    }
    review["live_quality"] = quality_live
    review["statements_note"] = statements_note
    review["statements_source"] = (
        statements.get("statements_source") if statements else None
    )
    review["profile_sector"] = profile.get("finnhubIndustry") or profile.get("industry")
    return review


@router.get("/{ticker}/ondemand")
def get_ondemand(ticker: str, db=Depends(get_db)):
    try:
        return _build_ondemand(ticker, db)
    except LookupError as e:
        status = 404 if e.code in ("invalid_ticker", "unknown_ticker", "no_data", "no_indicators") else 502
        raise HTTPException(status_code=status, detail={"error": e.code, "reason": e.reason})
    except Exception as e:
        logger.exception("on-demand review failed for %s", ticker)
        raise HTTPException(status_code=502, detail={"error": "ondemand_failed", "reason": str(e)})


@router.post("/{ticker}/ondemand/align")
def align_ondemand(ticker: str, body: dict = Body(...)):
    """Apply user alignment to on-demand proposals, stateless.

    The frontend persists the actions in localStorage per ticker
    plus date, the same pattern as the TwelveStep saved analyses,
    and re-sends them here on reload, so the locked result can
    be rebuilt without a backend row. Proposed scores alone
    never count as final; only aligned scores do.
    """
    from services.ondemand_review import apply_alignment

    proposals = (body or {}).get("proposals") or {}
    actions = (body or {}).get("actions") or {}
    result = apply_alignment(proposals, actions)
    return {
        "ticker": ticker.upper().strip(),
        "proposals": result["proposals"],
        "audit_trail": result["audit_trail"],
        "status": result["status"],
        "provisional": result["provisional"],
    }


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
    except Exception as e:
        # Named, not a bare 500: the tab shows the reason instead of a
        # blank card, and the log keeps the traceback for diagnosis.
        logger.exception("ticker lookup failed for %s", ticker)
        raise HTTPException(status_code=502, detail={
            "error": "lookup_failed",
            "reason": f"lookup_failed: {type(e).__name__}: {e}",
        })
