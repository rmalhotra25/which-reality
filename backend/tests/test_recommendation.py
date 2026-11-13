"""Tests for the Answer block recommendation (services/recommendation.py).

The recommendation is four tiers from explicit rules: Buy Big
needs a fresh catalyst plus quality plus a sound trend; Buy
Small needs quality plus a reasonable price plus a sound trend;
Sell fires on a broken trend, a weak long-term lane, a severe
governance or legal headwind, or heavy insider selling; Hold is
everything else. A missing input can only block a tier, never
trigger one. Catalyst detection is pinned with stubbed news; no
network is used.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import recommendation as rec
from services.recommendation import (
    build_recommendation,
    clear_recommendation_cache,
    decide_recommendation,
    detect_catalysts,
)


def _article(title, hours_ago=1, publisher="Test"):
    published = (datetime.now(timezone.utc)
                 - timedelta(hours=hours_ago)).isoformat()
    return {"title": title, "published_at": published,
            "publisher": publisher, "url": "https://example.com/x"}


def _base_inputs(**overrides):
    inputs = {
        "price": 200.0,
        "ma50": 190.0,
        "ma200": 180.0,
        "grade": "B",
        "longterm_verdict": "strong",
        "dcf_base": 220.0,
        "price_gauge": "Fair",
        "headwinds": [],
        "catalysts": [],
        "insider_signal": "quiet",
        "insider_heavy_sell": False,
        "analyst_mean_vs_now_pct": 10.0,
    }
    inputs.update(overrides)
    return inputs


# --- catalyst detection -----------------------------------------------------

def test_catalyst_earnings_beat_primary_beats_secondary():
    articles = [
        _article("Acme beats estimates as revenue jumps", hours_ago=5),
        _article("Acme beat the street", hours_ago=1),
    ]
    catalysts, note = detect_catalysts("ACME", articles=articles)
    assert note is None
    assert len(catalysts) == 1
    assert catalysts[0]["title"] == "Earnings beat"
    # The primary-keyword article wins even though it is older.
    assert "beats estimates" in catalysts[0]["detail"]


def test_catalyst_freshest_wins_within_primary():
    articles = [
        _article("Acme raised guidance for the year", hours_ago=10),
        _article("Acme raised guidance for next quarter", hours_ago=2),
    ]
    catalysts, _ = detect_catalysts("ACME", articles=articles)
    assert len(catalysts) == 1
    assert catalysts[0]["title"] == "Guidance raised"
    assert catalysts[0]["age_hours"] == 2.0


def test_catalyst_stale_beyond_seven_days_ignored():
    articles = [_article("Acme beats estimates", hours_ago=24 * 8)]
    catalysts, _ = detect_catalysts("ACME", articles=articles)
    assert catalysts == []


def test_catalyst_untimestamped_skipped():
    articles = [{"title": "Acme beats estimates", "published_at": None,
                 "publisher": "Test", "url": ""}]
    catalysts, _ = detect_catalysts("ACME", articles=articles)
    assert catalysts == []


def test_catalyst_one_per_category():
    articles = [
        _article("Acme wins contract with the Army", hours_ago=3),
        _article("Acme wins contract with the Navy", hours_ago=1),
    ]
    catalysts, _ = detect_catalysts("ACME", articles=articles)
    assert len(catalysts) == 1
    assert catalysts[0]["title"] == "Contract win"


def test_catalyst_word_boundary():
    # "sec" must not match inside "sector"; here the Approval
    # secondary keyword "approved" must not fire on "improved".
    articles = [_article("Acme improved margins this quarter", hours_ago=1)]
    catalysts, _ = detect_catalysts("ACME", articles=articles)
    assert catalysts == []


# --- decision rules ---------------------------------------------------------

def test_sell_on_broken_trend():
    out = decide_recommendation(_base_inputs(price=170.0))
    assert out["tier"] == "sell"
    assert "200-day" in out["reason"]
    assert "If you own it, sell" in out["if_you_own_it"]
    assert "don't buy it" in out["if_you_dont_own_it"]


def test_sell_on_weak_longterm():
    out = decide_recommendation(_base_inputs(longterm_verdict="weak"))
    assert out["tier"] == "sell"
    assert "long-term lane says weak" in out["reason"]


def test_sell_on_severe_headwind():
    out = decide_recommendation(_base_inputs(headwinds=[
        {"title": "Governance investigation", "strength": 3}]))
    assert out["tier"] == "sell"
    assert "governance investigation" in out["reason"]


def test_sell_on_heavy_insider_selling():
    out = decide_recommendation(_base_inputs(insider_heavy_sell=True))
    assert out["tier"] == "sell"
    assert "insiders are selling heavily" in out["reason"]


def test_sell_beats_buy_big():
    # A fresh catalyst does not rescue a broken trend.
    out = decide_recommendation(_base_inputs(
        price=170.0,
        catalysts=[{"title": "Earnings beat", "age_hours": 2.0}]))
    assert out["tier"] == "sell"


def test_buy_big_on_fresh_catalyst():
    out = decide_recommendation(_base_inputs(
        catalysts=[{"title": "Earnings beat", "age_hours": 5.0}]))
    assert out["tier"] == "buy_big"
    assert out["label"] == "Buy Big"
    assert "earnings beat" in out["reason"]
    assert "If you don't own it, buy big" in out["if_you_dont_own_it"]
    assert "If you own it, add" in out["if_you_own_it"]


def test_buy_big_blocked_without_quality():
    out = decide_recommendation(_base_inputs(
        grade="D", longterm_verdict="watch",
        catalysts=[{"title": "Earnings beat", "age_hours": 5.0}]))
    assert out["tier"] in ("buy_small", "hold")
    assert out["blocked_by"]


def test_buy_big_blocked_when_catalyst_stale():
    out = decide_recommendation(_base_inputs(
        catalysts=[{"title": "Earnings beat", "age_hours": 72.0}]))
    assert out["tier"] == "buy_small"


def test_buy_small_on_quality_and_valuation():
    out = decide_recommendation(_base_inputs())
    assert out["tier"] == "buy_small"
    assert "DCF base $220.00 is above the $200.00 price" in out["reason"]


def test_buy_small_blocked_when_valuation_rich():
    out = decide_recommendation(_base_inputs(
        dcf_base=150.0, price_gauge="Expensive", grade="B"))
    assert out["tier"] == "hold"
    assert "price is rich" in out["reason"]


def test_hold_when_quality_unverified():
    out = decide_recommendation(_base_inputs(
        grade=None, longterm_verdict="not_verified",
        dcf_base=None, price_gauge="Unknown"))
    assert out["tier"] == "hold"
    assert "quality is not verified" in out["reason"]


def test_hold_when_trend_unknown():
    out = decide_recommendation(_base_inputs(ma50=None, ma200=None))
    assert out["tier"] == "hold"
    assert "trend cannot be judged" in out["reason"]


def test_missing_inputs_never_trigger_sell():
    out = decide_recommendation({})
    assert out["tier"] == "hold"


# --- builder ----------------------------------------------------------------

def test_build_recommendation_wires_inputs(monkeypatch):
    clear_recommendation_cache()
    monkeypatch.setattr(rec, "_fetch_trend",
                        lambda ticker: (200.0, 190.0, 180.0, None))

    class _Story:
        @staticmethod
        def build_story(ticker):
            return {
                "status": "ok", "name": "Acme Corp", "grade": "B",
                "grade_reason": "Growth Strong, Margins Strong.",
                "targets": {"mean": 220.0, "low": 180.0, "high": 260.0,
                            "mean_vs_now_pct": 10.0,
                            "analysts": {"buy": 20, "hold": 5, "sell": 1,
                                         "total": 26},
                            "source": "yahoo"},
                "gauges": {"price": {"label": "Fair"}},
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

    monkeypatch.setattr(rec, "detect_catalysts",
                        lambda ticker: ([], None))

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

    payload = build_recommendation("ACME")
    assert payload["status"] == "ok"
    assert payload["ticker"] == "ACME"
    assert payload["recommendation"]["tier"] == "buy_small"
    assert payload["evidence"]["price"]["current"] == 200.0
    assert payload["evidence"]["analyst"]["buy"] == 20
    assert payload["evidence"]["roadmap"]["earnings_date"] == "2027-02-01"


def test_build_recommendation_no_price_unavailable(monkeypatch):
    clear_recommendation_cache()
    monkeypatch.setattr(rec, "_fetch_trend",
                        lambda ticker: (None, None, None, "no price history"))
    payload = build_recommendation("ZZZZ")
    assert payload["status"] == "unavailable"
