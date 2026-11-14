"""Top purchase candidates for the ticker lookup page.

The lookup page used to start with a long instruction banner and
nothing to look at until the user typed a ticker. Most tickers the
user types come back grade D or worse, because valuations are
stretched and the Story grade needs all four gauges favorable for
an A. This list flips that around: it grades a small universe
(the top 20 quality-screener survivors) and shows the best five
to consider buying, As first, then Bs to make five. Clicking one
loads it in the lookup, so the Answer block and the snapshot
explain why it is an A or B and why it is recommended to buy now.

Rules:
- Universe: backend/data/top_stocks_universe.json, the top 20
  screener survivors by composite score, refreshed with the
  Monday screener run. The file is only the universe, never a
  verdict: the Story grade and the recommendation tier are
  computed live per ticker.
- Ranking: Story grade A first, then B. Within the same grade,
  Buy Big first, then Buy Small, then Hold. The universe order
  (composite score) breaks ties, so the sort is stable. A Sell
  tier, or grade C, D, or F, never qualifies. Fewer than five
  qualifiers means a shorter list, never padding with lower
  grades.
- Caching: the graded list is cached for 6 hours, so the page
  loads fast and does not re-grade 20 tickers on every load.
  Each ticker is graded in parallel and guarded on its own, so
  one bad ticker never blocks the list.
- Quant decides: the grade comes from the Story service and the
  tier from the recommendation service, unchanged. This module
  only ranks what they return.
"""

import concurrent.futures
import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 6 * 3600
_CACHE_KEY = "top_stocks"
# One lock for the whole build: concurrent cold loads share a single
# computation instead of each grading 20 tickers for over a minute.
_BUILD_LOCK = threading.Lock()
_UNIVERSE_FILE = "top_stocks_universe.json"

_GRADE_RANK = {"A": 0, "B": 1}
_TIER_RANK = {"buy_big": 0, "buy_small": 1, "hold": 2}
_MAX_ITEMS = 5


def clear_top_stocks_cache():
    _CACHE.clear()


def load_universe():
    """The universe tickers from the repo data file.

    Returns [{ticker, composite}] in composite order, or [] when
    the file is missing or unreadable. A missing file means an
    empty list, never a guessed universe.
    """
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "data",
                            _UNIVERSE_FILE)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        tickers = payload.get("tickers") or []
        out = []
        for row in tickers:
            ticker = str(row.get("ticker") or "").upper().strip()
            if not ticker:
                continue
            try:
                composite = float(row.get("composite"))
            except (TypeError, ValueError):
                composite = None
            out.append({"ticker": ticker, "composite": composite})
        return out
    except Exception as exc:
        logger.warning("top stocks universe failed to load: %s", exc)
        return []


def rank_candidates(candidates):
    """Rank graded candidates and take the top five. Pure function.

    candidates are dicts with "grade" (Story letter) and "tier"
    (recommendation tier). Only grade A or B with tier Buy Big,
    Buy Small, or Hold qualify. Grade A comes first, then B;
    within a grade, Buy Big, then Buy Small, then Hold. The input
    order (universe composite order) breaks ties, so the sort is
    stable. Returns at most five, fewer when fewer qualify.
    """
    qualified = [
        c for c in (candidates or [])
        if (c or {}).get("grade") in _GRADE_RANK
        and (c or {}).get("tier") in _TIER_RANK
    ]
    qualified.sort(key=lambda c: (_GRADE_RANK[c["grade"]],
                                  _TIER_RANK[c["tier"]]))
    return qualified[:_MAX_ITEMS]


def _default_fetcher(ticker):
    """Grade and tier for one ticker from the Story and Answer services.

    Returns the list-item dict, or None when the ticker cannot be
    graded. Every failure is caught here, so one bad ticker never
    blocks the list.
    """
    try:
        from services import recommendation as rec_service
        from services import story as story_service

        story = story_service.build_story(ticker) or {}
        if story.get("status") != "ok":
            return None
        rec = rec_service.build_recommendation(ticker) or {}
        if rec.get("status") != "ok":
            return None
        decision = rec.get("recommendation") or {}
        insights = story.get("insights") or {}
        catalysts = ((rec.get("evidence") or {}).get("news") or {}).get("catalysts") or []
        catalyst = None
        if catalysts:
            first = catalysts[0] or {}
            catalyst = {"title": first.get("title"),
                        "age_hours": first.get("age_hours")}
        return {
            "ticker": ticker,
            "name": story.get("name") or ticker,
            "grade": story.get("grade"),
            "tier": decision.get("tier"),
            "tier_label": decision.get("label"),
            "reason": decision.get("reason"),
            "price": rec.get("price"),
            "growth_story": insights.get("growth_story"),
            "biggest_risk": insights.get("biggest_risk"),
            "earnings_date": story.get("earnings_date"),
            "catalyst": catalyst,
        }
    except Exception as exc:
        logger.warning("top stocks fetch failed for %s: %s", ticker, exc)
        return None


def _guarded(fetch, ticker):
    """One ticker's fetch, guarded: a raising fetcher returns None
    instead of breaking the list, the same as a bad ticker."""
    try:
        return fetch(ticker)
    except Exception as exc:
        logger.warning("top stocks fetch failed for %s: %s", ticker, exc)
        return None


def build_top_stocks(fetcher=None):
    """The top five purchase candidates, cached for 6 hours.

    fetcher(ticker) returns a candidate dict or None; the default
    fetcher grades from the Story and Answer services. The payload
    is {status, items, qualified_count, universe_size, note,
    as_of}. When fewer than five qualify, note says so plainly.
    Concurrent cold loads share one computation: the first caller
    holds the build lock, the rest wait and read the cache it fills.
    """
    cached = _CACHE.get(_CACHE_KEY)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    with _BUILD_LOCK:
        cached = _CACHE.get(_CACHE_KEY)
        if cached and time.time() - cached[0] < _CACHE_TTL:
            return cached[1]
        payload = _build_top_stocks_uncached(fetcher)
        _CACHE[_CACHE_KEY] = (time.time(), payload)
        return payload


def _build_top_stocks_uncached(fetcher=None):
    """Grade the universe and rank it, with no cache or lock.

    Only called from build_top_stocks while it holds the build lock.
    """
    fetch = fetcher or _default_fetcher
    universe = load_universe()
    candidates = []
    if universe:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(
                    lambda t: _guarded(fetch, t),
                    [u["ticker"] for u in universe]):
                if result is not None:
                    candidates.append(result)
    items = rank_candidates(candidates)
    note = None
    if len(items) < _MAX_ITEMS:
        note = (f"Only {len(items)} of the {len(universe)} stocks in "
                "the universe qualified as grade A or B with a Buy or "
                "Hold recommendation, so the list shows "
                f"{len(items)}.")
    return {
        "status": "ok",
        "items": items,
        "qualified_count": len(items),
        "universe_size": len(universe),
        "note": note,
        "as_of": time.strftime("%Y-%m-%d"),
    }
