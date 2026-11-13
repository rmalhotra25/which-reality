"""The Answer block for the ticker lookup: one recommendation.

The ticker lookup page was hard to use because it showed four
lanes at once (timing, long-term, DCA, options) with no single
answer. The Answer block sits at the top and gives one
recommendation in plain words, built from the same numbers the
lanes already compute, plus analyst ratings, news catalysts,
the company roadmap, and insider activity.

Recommendation tiers, in plain language:
- Buy Big: a fresh, direct catalyst landed (earnings beat,
  guidance raised, approval, contract win) and the company is
  strong, so this is the moment to buy in size.
- Buy Small: no immediate catalyst, but the long-term case is
  strong and the price is reasonable, so accumulate over time.
- Hold: the thesis is intact but there is no reason to add
  today, and no reason to sell.
- Sell: the reason to own it has broken down (trend broken,
  long-term weak, a governance or legal headwind, or insiders
  selling heavily).

The recommendation is framed conditionally, because TradeIQ
does not track what the user owns: every tier carries an
"if you own it" line and an "if you don't own it" line. The
same tier answers both cases.

Quant decides: the tiers come from explicit rules below, not
from Claude. The inputs come from the Story (price, analyst
targets, gauges, headwinds, DCF, grade), the alert engine
(trend), Polygon news (catalysts), the earnings calendar
(roadmap), and the insider service (Form 4 activity). Missing
data is reported, never invented, and a missing input can only
block a tier, never trigger one.
"""

import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 3600
_CACHE_MAX_ENTRIES = 100

# A catalyst only drives Buy Big while it is fresh: 48 hours.
_CATALYST_FRESH_HOURS = 48
# Catalysts are shown as evidence for a week after they land.
_CATALYST_EVIDENCE_DAYS = 7
_NEWS_LIMIT = 30

# Positive catalyst categories. Same pattern as the Story news
# headwinds: primary keywords beat secondary-only matches, the
# freshest wins within that, one catalyst per category. A title
# alone cannot prove the catalyst (a "beat" headline could be
# about a competitor), so the evidence line always shows the
# headline and the recommendation still requires quality and
# trend, so a false positive alone cannot trigger Buy Big.
_CATALYST_CATEGORIES = (
    {
        "title": "Earnings beat",
        "primary": ("beat estimates", "beats estimates", "beat expectations",
                    "beats expectations", "topped estimates",
                    "exceeded expectations", "earnings beat"),
        "secondary": ("beat", "beats", "topped", "strong results",
                      "better than expected"),
        "strength": 3,
    },
    {
        "title": "Guidance raised",
        "primary": ("raised guidance", "raises guidance", "raises outlook",
                    "lifts forecast", "raised its outlook",
                    "raises full-year", "raised full-year"),
        "secondary": ("outlook raised", "guidance up", "forecast raised",
                      "lifts outlook"),
        "strength": 3,
    },
    {
        "title": "Approval",
        "primary": ("fda approval", "fda approved", "approved by the fda",
                    "fda clearance", "fda authorized"),
        "secondary": ("approved", "clearance", "authorized", "green light"),
        "strength": 3,
    },
    {
        "title": "Contract win",
        "primary": ("wins contract", "wins a contract", "awarded contract",
                    "awarded a contract", "wins deal", "partnership"),
        "secondary": ("signs deal", "agreement", "collaboration",
                      "selected by"),
        "strength": 2,
    },
    {
        "title": "Buyback or dividend",
        "primary": ("buyback", "share repurchase", "dividend increase",
                    "initiates dividend", "special dividend",
                    "raises dividend"),
        "secondary": ("returns capital", "shareholder return",
                      "repurchase program"),
        "strength": 2,
    },
)


def _cache_get(ticker: str):
    row = _CACHE.get(ticker)
    if row and time.time() - row[0] < _CACHE_TTL:
        return row[1]
    return None


def _cache_put(ticker: str, payload: dict):
    from services.cache_utils import bounded_put

    bounded_put(_CACHE, ticker, payload, now=time.time(),
                ttl_seconds=_CACHE_TTL, max_entries=_CACHE_MAX_ENTRIES)


def clear_recommendation_cache():
    _CACHE.clear()


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _keyword_re(keyword):
    if " " in keyword:
        return re.compile(re.escape(keyword))
    return re.compile(r"\b" + re.escape(keyword) + r"\b")


def _compile_catalyst_patterns():
    compiled = []
    for category in _CATALYST_CATEGORIES:
        pats = [(_keyword_re(k), True) for k in category["primary"]]
        pats += [(_keyword_re(k), False) for k in category["secondary"]]
        compiled.append((category, pats))
    return compiled


_CATALYST_PATTERNS = _compile_catalyst_patterns()


def _parse_news_date(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def detect_catalysts(ticker, articles=None):
    """Positive catalysts from recent company news.

    Returns [{title, detail, strength, age_hours, url}]. One per
    category, the clearest fresh article: a primary-keyword match
    beats a secondary-only one, freshest wins within that. Only
    articles within _CATALYST_EVIDENCE_DAYS count. An article with
    no timestamp is unverifiable and skipped. A news outage returns
    ([], note), never an exception.
    """
    if articles is None:
        try:
            from services.polygon_client import get_news

            articles = get_news(ticker, limit=_NEWS_LIMIT) or []
            note = None
        except Exception as exc:
            logger.warning("recommendation news failed for %s: %s",
                           ticker, exc)
            return [], "company news unavailable"
    else:
        note = None
    now = datetime.now(timezone.utc)
    fresh = []
    for article in articles or []:
        published = _parse_news_date(article.get("published_at"))
        if published is None:
            continue
        age = now - published
        if age.days > _CATALYST_EVIDENCE_DAYS:
            continue
        title = (article.get("title") or "").strip()
        if not title:
            continue
        fresh.append((published, article))
    catalysts = []
    for category, pats in _CATALYST_PATTERNS:
        best = None
        for published, article in fresh:
            low = (article.get("title") or "").lower()
            primary = any(p.search(low) for p, is_primary in pats
                          if is_primary)
            secondary = any(p.search(low) for p, is_primary in pats
                            if not is_primary)
            if not primary and not secondary:
                continue
            key = (2 if primary else 1, published)
            if best is None or key > best[0]:
                best = (key, published, article)
        if best is None:
            continue
        _, published, article = best
        headline = (article.get("title") or "").strip()
        if len(headline) > 140:
            headline = headline[:137] + "..."
        publisher = (article.get("publisher") or "").strip()
        day = published.strftime("%b %d, %Y").replace(" 0", " ")
        detail = headline
        if publisher:
            detail += f" ({publisher}, {day})"
        else:
            detail += f" ({day})"
        age_hours = round((now - published).total_seconds() / 3600.0, 1)
        entry = {"title": category["title"], "detail": detail,
                 "strength": category["strength"],
                 "age_hours": age_hours}
        url = (article.get("url") or "").strip()
        if url:
            entry["url"] = url
        catalysts.append(entry)
    return catalysts, note


# ---------------------------------------------------------------------------
# The decision rules. Pure function of the inputs, directly testable.
# ---------------------------------------------------------------------------

_TIER_LABELS = {
    "buy_big": "Buy Big",
    "buy_small": "Buy Small",
    "hold": "Hold",
    "sell": "Sell",
}

_TIER_OWN_LINES = {
    "buy_big": "If you own it, add to your position: the catalyst supports buying more.",
    "buy_small": "If you own it, keep holding and add small amounts on dips.",
    "hold": "If you own it, hold what you own: the thesis is intact, no reason to sell.",
    "sell": "If you own it, sell: the reason to own it has broken down.",
}

_TIER_DONT_OWN_LINES = {
    "buy_big": "If you don't own it, buy big: a catalyst just landed and the company is strong.",
    "buy_small": "If you don't own it, buy small amounts over time: the long-term case is strong, no rush.",
    "hold": "If you don't own it, don't chase it now: no catalyst, no reason to start a position today.",
    "sell": "If you don't own it, don't buy it: the trend is broken or a headwind is in play.",
}


def decide_recommendation(inputs: dict):
    """One recommendation tier from the inputs. Deterministic.

    inputs keys (all optional; a missing input can only block a
    tier, never trigger one):
      price, ma50, ma200: floats or None.
      grade: Story letter grade A-F or None.
      longterm_verdict: strong/watch/weak/blocked/not_verified or None.
      dcf_base: float or None.
      price_gauge: Cheap/Fair/Expensive/Unknown or None.
      headwinds: [{title, strength}] (Story headwinds).
      catalysts: [{title, age_hours}] from detect_catalysts.
      insider_signal: buying/selling/mixed/quiet or None.
      insider_heavy_sell: bool.
      analyst_mean_vs_now_pct: float or None.
    Returns {tier, label, reason, if_you_own_it, if_you_dont_own_it,
    blocked_by}.
    """
    price = _finite(inputs.get("price"))
    ma50 = _finite(inputs.get("ma50"))
    ma200 = _finite(inputs.get("ma200"))
    grade = inputs.get("grade")
    longterm_verdict = inputs.get("longterm_verdict")
    dcf_base = _finite(inputs.get("dcf_base"))
    price_gauge = inputs.get("price_gauge")
    headwinds = inputs.get("headwinds") or []
    catalysts = inputs.get("catalysts") or []
    insider_heavy_sell = bool(inputs.get("insider_heavy_sell"))

    # Trend: broken when the price is below its 200-day average.
    # When the 200-day is unknown, the 50-day decides; when both
    # are unknown, the trend cannot block anything.
    trend_broken = False
    trend_unknown = True
    if price is not None and ma200 is not None:
        trend_broken = price < ma200
        trend_unknown = False
    elif price is not None and ma50 is not None:
        trend_broken = price < ma50
        trend_unknown = False

    quality = grade in ("A", "B") or longterm_verdict == "strong"
    valuation_ok = (
        (dcf_base is not None and price is not None and dcf_base > price)
        or price_gauge in ("Cheap", "Fair")
        or grade == "A"
    )

    # A fresh catalyst: within 48 hours.
    fresh_catalysts = [c for c in catalysts
                       if (c.get("age_hours") or 9999) <= _CATALYST_FRESH_HOURS]
    fresh_catalyst = fresh_catalysts[0] if fresh_catalysts else None

    # A governance or legal headwind at full strength is a SELL
    # trigger on its own: the thesis has a hole no number shows yet.
    severe_headwind = None
    for h in headwinds:
        if h.get("strength", 1) >= 3 and h.get("title") in (
                "Governance investigation", "Legal action"):
            severe_headwind = h
            break

    blocked_by = []

    # --- SELL ---------------------------------------------------------------
    sell_reasons = []
    if trend_broken:
        sell_reasons.append("the price is below its 200-day average")
    if longterm_verdict == "weak":
        sell_reasons.append("the long-term lane says weak")
    if severe_headwind is not None:
        sell_reasons.append(
            f"a {severe_headwind['title'].lower()} is open")
    if insider_heavy_sell:
        sell_reasons.append("insiders are selling heavily")
    if sell_reasons:
        tier = "sell"
        reason = ("Sell: " + "; ".join(sell_reasons) + ".")
        return {"tier": tier, "label": _TIER_LABELS[tier], "reason": reason,
                "if_you_own_it": _TIER_OWN_LINES[tier],
                "if_you_dont_own_it": _TIER_DONT_OWN_LINES[tier],
                "blocked_by": blocked_by}

    # --- BUY BIG ------------------------------------------------------------
    if fresh_catalyst is not None:
        if not quality:
            blocked_by.append("no fresh catalyst buy: quality is not verified")
        elif trend_broken or trend_unknown:
            blocked_by.append("no fresh catalyst buy: the trend is broken or unknown")
        else:
            tier = "buy_big"
            reason = (f"Buy Big: a {fresh_catalyst['title'].lower()} "
                      f"landed {fresh_catalyst['age_hours']} hours ago and "
                      "the company is strong.")
            return {"tier": tier, "label": _TIER_LABELS[tier],
                    "reason": reason,
                    "if_you_own_it": _TIER_OWN_LINES[tier],
                    "if_you_dont_own_it": _TIER_DONT_OWN_LINES[tier],
                    "blocked_by": blocked_by}

    # --- BUY SMALL ----------------------------------------------------------
    if quality and valuation_ok and not trend_broken and not trend_unknown:
        tier = "buy_small"
        parts = ["Buy Small: the long-term case is strong"]
        if dcf_base is not None and price is not None and dcf_base > price:
            parts.append(f"and the DCF base ${dcf_base:.2f} is above "
                         f"the ${price:.2f} price")
        elif price_gauge in ("Cheap", "Fair"):
            parts.append(f"and valuation reads {price_gauge.lower()}")
        reason = " ".join(parts) + ", so accumulate over time."
        return {"tier": tier, "label": _TIER_LABELS[tier],
                "reason": reason,
                "if_you_own_it": _TIER_OWN_LINES[tier],
                "if_you_dont_own_it": _TIER_DONT_OWN_LINES[tier],
                "blocked_by": blocked_by}

    # --- HOLD ---------------------------------------------------------------
    tier = "hold"
    if trend_unknown:
        reason = ("Hold: the trend cannot be judged from the data "
                  "available, so there is no reason to act today.")
    elif not quality:
        reason = ("Hold: quality is not verified, so there is no "
                  "reason to start or add to a position today.")
    elif not valuation_ok:
        reason = ("Hold: the company is strong but the price is "
                  "rich, so there is no reason to add today.")
    else:
        reason = ("Hold: the thesis is intact but there is no fresh "
                  "catalyst, so there is no reason to add today.")
    return {"tier": tier, "label": _TIER_LABELS[tier], "reason": reason,
            "if_you_own_it": _TIER_OWN_LINES[tier],
            "if_you_dont_own_it": _TIER_DONT_OWN_LINES[tier],
            "blocked_by": blocked_by}


# ---------------------------------------------------------------------------
# Builder: fetch the inputs from the services that already compute them.
# ---------------------------------------------------------------------------

def _fetch_trend(ticker):
    """Price, 50-day and 200-day averages from the alert engine."""
    try:
        import services.alert_engine as ae

        df = ae._fetch_ohlcv(ticker)
        if df is None:
            return None, None, None, "no price history found"
        ind = ae._indicators(df)
        if ind is None or ind.get("price") is None:
            return None, None, None, "not enough history to compute indicators"
        price = _finite(ind.get("price"))
        ma50 = _finite(ind.get("ma50"))
        ma200 = _finite(ind.get("ma200"))
        return price, ma50, ma200, None
    except Exception as exc:
        logger.warning("recommendation trend failed for %s: %s", ticker, exc)
        return None, None, None, f"trend fetch failed: {exc}"


def build_recommendation(ticker: str):
    """The Answer block payload for one ticker."""
    ticker = (ticker or "").upper().strip()
    cached = _cache_get(ticker)
    if cached is not None:
        return cached
    notes = []

    price, ma50, ma200, trend_error = _fetch_trend(ticker)
    if price is None:
        payload = {"status": "unavailable", "ticker": ticker,
                   "reason": trend_error or "no price available"}
        _cache_put(ticker, payload)
        return payload

    try:
        from services import story as story_service

        story = story_service.build_story(ticker) or {}
    except Exception as exc:
        logger.warning("recommendation story failed for %s: %s", ticker, exc)
        story = {}
    if story.get("status") != "ok":
        story = {}

    try:
        from services import insider as insider_service

        insider = insider_service.fetch_insider(ticker) or {}
    except Exception as exc:
        logger.warning("recommendation insider failed for %s: %s",
                       ticker, exc)
        insider = {}
    insider_summary = insider.get("summary") or {}

    catalysts, catalyst_note = detect_catalysts(ticker)
    if catalyst_note:
        notes.append(catalyst_note)

    targets = story.get("targets") or {}
    gauges = story.get("gauges") or {}
    price_gauge = (gauges.get("price") or {}).get("label")
    dcf = story.get("dcf") or {}
    headwinds = story.get("headwinds") or []
    earnings_date = story.get("earnings_date")
    earnings_days = None
    if earnings_date:
        try:
            from datetime import date as _date

            earnings_days = (_date.fromisoformat(earnings_date)
                             - _date.today()).days
        except (TypeError, ValueError):
            earnings_days = None

    inputs = {
        "price": price,
        "ma50": ma50,
        "ma200": ma200,
        "grade": story.get("grade"),
        "longterm_verdict": story.get("longterm_verdict"),
        "dcf_base": dcf.get("base"),
        "price_gauge": price_gauge,
        "headwinds": headwinds,
        "catalysts": catalysts,
        "insider_signal": insider_summary.get("signal"),
        "insider_heavy_sell": insider_summary.get("heavy_sell", False),
        "analyst_mean_vs_now_pct": targets.get("mean_vs_now_pct"),
    }
    decision = decide_recommendation(inputs)

    analysts = targets.get("analysts") or {}
    evidence = {
        "price": {
            "current": round(price, 2),
            "ma50": round(ma50, 2) if ma50 is not None else None,
            "ma200": round(ma200, 2) if ma200 is not None else None,
            "above_ma50": (price >= ma50) if ma50 is not None else None,
            "above_ma200": (price >= ma200) if ma200 is not None else None,
            "week52": story.get("week52"),
        },
        "analyst": {
            "mean": targets.get("mean"),
            "low": targets.get("low"),
            "high": targets.get("high"),
            "mean_vs_now_pct": targets.get("mean_vs_now_pct"),
            "buy": analysts.get("buy"),
            "hold": analysts.get("hold"),
            "sell": analysts.get("sell"),
            "total": analysts.get("total"),
            "source": targets.get("source"),
            "dcf_base": dcf.get("base"),
            "dcf_bear": dcf.get("bear"),
            "dcf_bull": dcf.get("bull"),
        },
        "news": {
            "headwinds": [
                {"title": h.get("title"), "detail": h.get("detail"),
                 "strength": h.get("strength"), "source": h.get("source")}
                for h in headwinds
            ],
            "catalysts": catalysts,
        },
        "insider": {
            "source": insider.get("source"),
            "summary": insider_summary,
            "note": insider.get("reason") or insider.get("note"),
        },
        "roadmap": {
            "earnings_date": earnings_date,
            "earnings_days_away": earnings_days,
            "earnings_unknown": story.get("earnings_unknown", True),
            "grade": story.get("grade"),
            "grade_reason": story.get("grade_reason"),
            "longterm_verdict": story.get("longterm_verdict"),
            "what_would_change": story.get("what_would_change"),
        },
    }
    if story.get("notes"):
        notes.extend(story["notes"])

    payload = {
        "status": "ok",
        "ticker": ticker,
        "name": story.get("name") or ticker,
        "price": round(price, 2),
        "recommendation": decision,
        "evidence": evidence,
        "notes": notes,
    }
    _cache_put(ticker, payload)
    return payload
