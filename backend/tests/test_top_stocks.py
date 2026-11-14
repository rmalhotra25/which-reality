"""Tests for the Top 5 purchase candidates (services/top_stocks.py).

The list grades the top 20 quality-screener survivors and shows
the best five to consider buying: grade A first, then B, Buy Big
before Buy Small before Hold within a grade. Sell and grade C, D,
or F never qualify, and fewer than five qualifiers means a
shorter list, never padding. Live fetching is stubbed; no network
is used.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.top_stocks import (
    build_top_stocks,
    clear_top_stocks_cache,
    load_universe,
    rank_candidates,
)


def _cand(ticker, grade, tier):
    return {"ticker": ticker, "grade": grade, "tier": tier}


# --- universe ---------------------------------------------------------------

def test_universe_loads_twenty_in_composite_order():
    universe = load_universe()
    assert len(universe) == 20
    assert universe[0]["ticker"] == "NVDA"
    assert universe[0]["composite"] == 92.7
    assert universe[-1]["ticker"] == "RMD"
    composites = [u["composite"] for u in universe]
    assert composites == sorted(composites, reverse=True)


# --- ranking ----------------------------------------------------------------

def test_ranking_a_before_b_and_buy_big_first():
    out = rank_candidates([
        _cand("BBB", "B", "buy_big"),
        _cand("AAA", "A", "hold"),
        _cand("AAB", "A", "buy_big"),
        _cand("AAS", "A", "buy_small"),
        _cand("BBS", "B", "buy_small"),
        _cand("BBH", "B", "hold"),
    ])
    assert [c["ticker"] for c in out] == [
        "AAB", "AAS", "AAA", "BBB", "BBS"]
    # The sixth candidate is cut by the five-item cap, not by rank.


def test_ranking_excludes_sell_and_c_d_f_grades():
    out = rank_candidates([
        _cand("SELLA", "A", "sell"),
        _cand("C1", "C", "buy_big"),
        _cand("D1", "D", "buy_big"),
        _cand("F1", "F", "buy_big"),
        _cand("OK", "B", "buy_small"),
    ])
    assert [c["ticker"] for c in out] == ["OK"]


def test_ranking_caps_at_five_and_keeps_universe_order_on_ties():
    cands = [_cand(f"T{i:02d}", "B", "buy_small") for i in range(8)]
    out = rank_candidates(cands)
    assert len(out) == 5
    assert [c["ticker"] for c in out] == ["T00", "T01", "T02", "T03", "T04"]


def test_ranking_empty_and_none_input():
    assert rank_candidates([]) == []
    assert rank_candidates(None) == []


# --- builder ----------------------------------------------------------------

def _stub_item(ticker, grade, tier):
    return {
        "ticker": ticker, "name": ticker + " Corp", "grade": grade,
        "tier": tier,
        "tier_label": {"buy_big": "Buy Big", "buy_small": "Buy Small",
                       "hold": "Hold", "sell": "Sell"}[tier],
        "reason": "Buy Small: the long-term case is strong.",
        "price": 100.0,
        "growth_story": "Sales are growing fast at 30.0% a year.",
        "biggest_risk": "No single risk stands out.",
        "earnings_date": "2027-02-22",
        "catalyst": None,
    }


def test_builder_returns_top_five_with_counts():
    clear_top_stocks_cache()
    plan = {"NVDA": ("A", "buy_small"), "PLTR": ("B", "buy_big"),
            "ANET": ("A", "buy_big"), "MU": ("B", "hold"),
            "SNDK": ("B", "buy_small"), "DOCS": ("A", "hold"),
            "YOU": ("C", "buy_big")}
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if ticker not in plan:
            return None
        grade, tier = plan[ticker]
        return _stub_item(ticker, grade, tier)

    out = build_top_stocks(fetcher=fetch)
    assert out["status"] == "ok"
    assert out["universe_size"] == 20
    assert out["qualified_count"] == 5
    assert out["note"] is None
    assert [i["ticker"] for i in out["items"]] == [
        "ANET", "NVDA", "DOCS", "PLTR", "SNDK"]
    assert len(calls) == 20


def test_builder_fewer_than_five_reports_qualified_count_and_note():
    clear_top_stocks_cache()
    plan = {"NVDA": ("A", "buy_small"), "PLTR": ("B", "hold")}

    def fetch(ticker):
        if ticker not in plan:
            return None
        grade, tier = plan[ticker]
        return _stub_item(ticker, grade, tier)

    out = build_top_stocks(fetcher=fetch)
    assert out["qualified_count"] == 2
    assert out["universe_size"] == 20
    assert [i["ticker"] for i in out["items"]] == ["NVDA", "PLTR"]
    assert out["note"] is not None
    assert "2 of the 20" in out["note"]
    assert "shows 2" in out["note"]


def test_builder_none_qualified_returns_empty_list_with_note():
    clear_top_stocks_cache()
    out = build_top_stocks(fetcher=lambda ticker: None)
    assert out["items"] == []
    assert out["qualified_count"] == 0
    assert "0 of the 20" in out["note"]


def test_builder_raising_fetcher_does_not_break_the_list():
    clear_top_stocks_cache()

    def fetch(ticker):
        if ticker == "NVDA":
            return _stub_item("NVDA", "A", "buy_small")
        raise RuntimeError("boom")

    out = build_top_stocks(fetcher=fetch)
    assert [i["ticker"] for i in out["items"]] == ["NVDA"]
    assert out["qualified_count"] == 1


def test_builder_caches_second_call_within_ttl():
    clear_top_stocks_cache()
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        if ticker == "NVDA":
            return _stub_item("NVDA", "A", "buy_small")
        return None

    first = build_top_stocks(fetcher=fetch)
    second = build_top_stocks(fetcher=fetch)
    assert first is second
    assert len(calls) == 20
    clear_top_stocks_cache()
    third = build_top_stocks(fetcher=fetch)
    assert third is not first
    assert len(calls) == 40


def test_builder_item_has_the_row_fields():
    clear_top_stocks_cache()
    out = build_top_stocks(
        fetcher=lambda t: _stub_item("NVDA", "A", "buy_small")
        if t == "NVDA" else None)
    item = out["items"][0]
    for field in ("ticker", "name", "grade", "tier", "tier_label",
                  "reason", "price", "growth_story", "biggest_risk",
                  "earnings_date"):
        assert item[field] is not None, field
    assert item["ticker"] == "NVDA"
    assert item["grade"] == "A"
    assert item["tier"] == "buy_small"


def test_no_em_dash_in_any_new_string():
    clear_top_stocks_cache()
    out = build_top_stocks(
        fetcher=lambda t: _stub_item("NVDA", "A", "buy_small")
        if t == "NVDA" else None)

    def _walk(value):
        if isinstance(value, str):
            assert "\u2014" not in value, value
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(out)


# --- the six buyer questions ------------------------------------------------
# A buyer deciding whether to buy needs six answers, and the
# click-through (Answer block plus snapshot) must carry all six
# without opening Full detail. This pins the fields each question
# reads, using the real builders with stubbed fetchers.

def test_six_buyer_questions_have_a_source(monkeypatch):
    from services import recommendation as rec
    from services.recommendation import build_recommendation
    from services.story import build_insights, clear_story_cache

    clear_story_cache()
    rec.clear_recommendation_cache()
    monkeypatch.setattr(rec, "_fetch_trend",
                        lambda ticker: (200.0, 190.0, 180.0, [180.0, 190.0, 200.0], None))

    class _Story:
        @staticmethod
        def build_story(ticker):
            return {
                "status": "ok", "name": "Acme Corp", "grade": "A",
                "grade_reason": "Growth Strong, Margins Strong.",
                "targets": {"mean": 220.0, "low": 180.0, "high": 260.0,
                            "mean_vs_now_pct": 10.0,
                            "analysts": {"buy": 20, "hold": 5, "sell": 1,
                                         "total": 26},
                            "source": "yahoo"},
                "gauges": {"price": {"label": "Fair"},
                           "growth": {"label": "Strong"},
                           "margins": {"label": "Strong"},
                           "debt": {"label": "Low"}},
                "headwinds": [],
                "dcf": {"base": 220.0, "bear": 180.0, "bull": 260.0,
                        "verdict": "strong"},
                "longterm_verdict": "strong",
                "earnings_date": "2027-02-01",
                "earnings_unknown": False,
                "week52": {"low": 150.0, "high": 250.0,
                           "position_pct": 50.0},
                "what_would_change": "What would change this assessment: if growth slows.",
                "notes": [],
            }

    import services.story as story_module
    monkeypatch.setattr(story_module, "build_story", _Story.build_story)

    class _Insider:
        @staticmethod
        def fetch_insider(ticker):
            return {"status": "ok", "source": "edgar",
                    "summary": {"signal": "quiet", "net_value": 0,
                                "buys": {"count": 0, "value": 0},
                                "sells": {"count": 0, "value": 0},
                                "heavy_sell": False, "notable": []}}

    import services.insider as insider_module
    monkeypatch.setattr(insider_module, "fetch_insider",
                        _Insider.fetch_insider)
    monkeypatch.setattr(
        rec, "detect_catalysts",
        lambda ticker: ([{"title": "Earnings beat",
                          "detail": "Beat estimates.",
                          "strength": 3, "age_hours": 5.0}], None))

    payload = build_recommendation("ACME")
    assert payload["status"] == "ok"
    evidence = payload["evidence"]
    # (1) Is it a good business: the Story grade.
    assert evidence["roadmap"]["grade"] == "A"
    # (2) Is the price right: analyst mean and DCF base.
    assert evidence["analyst"]["mean"] == 220.0
    assert evidence["analyst"]["dcf_base"] == 220.0
    # (3) Is the trend with me: price vs 50-day and 200-day.
    assert evidence["price"]["ma50"] == 190.0
    assert evidence["price"]["ma200"] == 180.0
    assert evidence["price"]["above_ma50"] is True
    assert evidence["price"]["above_ma200"] is True
    # (4) Why now: the fresh catalyst and the tier reason.
    assert evidence["news"]["catalysts"][0]["title"] == "Earnings beat"
    assert payload["recommendation"]["tier"] == "buy_big"
    assert "earnings beat" in payload["recommendation"]["reason"]
    # (6) What would change the call: the invalidation line.
    assert evidence["roadmap"]["what_would_change"].startswith(
        "What would change this assessment")

    # (1) and (5) also live in the snapshot insight lines, built
    # from the same Story data.
    insights = build_insights(
        "Acme Corp", "Technology", "Software", None, 0.30, 0.80, 0.30,
        {"growth": {"label": "Strong"}, "margins": {"label": "Strong"},
         "debt": {"label": "Low"}, "price": {"label": "Fair"}},
        [], {"low": 150.0, "high": 250.0, "position_pct": 50.0})
    assert "growing fast at 30.0% a year" in insights["growth_story"]
    assert insights["biggest_risk"]
    assert insights["biggest_risk"] != ""
