"""Tests for the on-demand ticker review (ondemand_review).

Run directly, no pytest in the sandbox:
  python3 -m backend.tests.test_ticker_lookup_ondemand
or with the small runner used by the other ticker lookup tests.
Pure functions only, no live network.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ondemand_review import (
    apply_alignment,
    build_dca_decision,
    build_ondemand_review,
    propose_ceo,
    propose_market_size,
    propose_moat,
    score_live_quality,
)


def _quality(**overrides):
    base = {
        "market_cap": 2_000_000_000_000,
        "fcf_ttm": 80_000_000_000,
        "total_debt": 20_000_000_000,
        "cash": 40_000_000_000,
        "operating_margin_ttm": 45.0,
        "gross_margin_ttm": 65.0,
        "roic": 28.0,
        "fcf_conversion": 1.0,
        "debt_to_ebitda": 0.2,
        "interest_coverage": 12.0,
        "rev_cagr_3y": 20.0,
        "fcf_margin_avg_3y": 30.0,
        "fcf_positive_years": 4,
        "rev_growth_pos_years": 3,
        "rev_growth_range": 10.0,
        "fcf_margin_range": 8.0,
        "fcf_yield": 4.0,
        "peg": 1.2,
        "ev_to_ebitda": 20.0,
        "above_200d": True,
        "short_pct": 2.0,
        "misses": 0,
    }
    base.update(overrides)
    return score_live_quality(base)


def _trend(price=100.0, ma50=95.0, ma200=90.0, above50=True, above200=True,
           ma50_dir="rising", ma200_dir="rising"):
    return {
        "ma50": ma50, "ma200": ma200,
        "above_ma50": above50, "above_ma200": above200,
        "ma50_direction": ma50_dir, "ma200_direction": ma200_dir,
    }


def _longterm(quality, verdict, base=None, reason_code=None):
    dcf = None
    if base is not None:
        dcf = {"fair_value": {"base": base, "bull": base * 1.3, "bear": base * 0.7}}
    return {
        "verdict": verdict, "label": verdict.upper(),
        "reason": f"test {verdict}", "reason_code": reason_code,
        "quality": quality, "dcf": dcf,
    }


def test_live_quality_weights():
    q = _quality()
    assert q["status"] == "verified", q
    assert q["composite"] is not None
    assert q["label"] in ("Compounder", "Steady", "Cyclical"), q
    # 40% Rule of 40: CAGR 20 + margin 30 = 50. Quality parts:
    # ROIC 28/30=93.3, op margin (45-20)/30=83.3, gross (65-30)/40=87.5,
    # conversion 1.0/1.2=83.3, debt 100, interest 100 -> avg 91.2.
    # Consistency: 100, 100, 100 -> 100. Valuation: yield 50, peg 60,
    # ev 80, above 100 -> 72.5. Composite = 0.4*50 + 0.3*91.2 + 0.2*100 + 0.1*72.5 = 74.6.
    assert abs(q["composite"] - 74.6) < 0.2, q["composite"]


def test_live_quality_missing_core_is_not_verified_not_zero():
    q = score_live_quality({"operating_margin_ttm": 45.0})
    assert q["status"] == "not_verified", q
    assert q["composite"] is None, q
    assert "market_cap" in q["missing"], q
    assert "fcf_ttm" in q["missing"], q


def test_short_interest_reported_twice_not_conflated():
    q = _quality(short_pct=15.0)
    kills = q["kills"]
    assert kills["short_interest_nash_kill_above_10"] is True, kills
    assert kills["short_interest_screener_kill_above_20"] is False, kills
    q2 = _quality(short_pct=25.0)
    assert q2["kills"]["short_interest_nash_kill_above_10"] is True
    assert q2["kills"]["short_interest_screener_kill_above_20"] is True
    q3 = _quality(short_pct=None)
    assert q3["kills"]["short_interest_nash_kill_above_10"] is False
    assert "short_pct" in q3["missing"], q3


def test_dca_now_strong_near_support():
    q = _quality()
    lt = _longterm(q, "strong", base=120.0)
    # Price 94 is below the 50-day average of 95, so it is near
    # support under the existing DCA rule.
    d = build_dca_decision(94.0, _trend(), lt, "wait")
    assert d["decision"] == "now", d
    assert d["plan"] is not None, d
    assert d["label"] == "BEGIN DCA NOW", d


def test_dca_now_quality_only_when_dcf_blocked_missing_statements():
    q = _quality()
    lt = _longterm(q, "blocked", reason_code="missing_statements")
    d = build_dca_decision(94.0, _trend(), lt, "wait")
    assert d["decision"] == "now", d


def test_dca_later_price_not_near_support():
    q = _quality()
    lt = _longterm(q, "strong", base=120.0)
    # Price 200, ma50 95, ma200 90: not below ma50, not within 3% above ma200.
    d = build_dca_decision(200.0, _trend(price=200.0), lt, "wait")
    assert d["decision"] == "later", d
    assert d["trigger_price"] == 95.0, d
    assert "50-day" in d["trigger"], d


def test_dca_later_watch_only_bull_above():
    q = _quality()
    lt = _longterm(q, "watch", base=90.0)
    d = build_dca_decision(100.0, _trend(), lt, "wait")
    assert d["decision"] == "later", d
    assert d["trigger_price"] == 90.0, d


def test_dca_avoid_trend_broken():
    q = _quality()
    lt = _longterm(q, "strong", base=120.0)
    trend = _trend(above50=False, above200=False, ma200_dir="falling")
    d = build_dca_decision(100.0, trend, lt, "avoid")
    assert d["decision"] == "avoid", d
    assert "trend broken" in d["killing_parameters"], d


def test_dca_avoid_weak_overvalued():
    q = _quality()
    lt = _longterm(q, "weak", base=80.0)
    d = build_dca_decision(100.0, _trend(), lt, "wait")
    assert d["decision"] == "avoid", d
    assert "DCF overvalued" in d["killing_parameters"], d


def test_dca_avoid_core_nash_kill():
    q = _quality(operating_margin_ttm=10.0)
    lt = _longterm(q, "strong", base=120.0)
    d = build_dca_decision(100.0, _trend(), lt, "wait")
    assert d["decision"] == "avoid", d
    assert any("operating margin" in k for k in d["killing_parameters"]), d


def test_dca_cannot_judge_missing_quality():
    q = score_live_quality({})
    lt = _longterm(q, "not_verified")
    d = build_dca_decision(100.0, _trend(), lt, "wait")
    assert d["decision"] == "cannot_judge", d


def test_alignment_provisional_until_aligned():
    proposals = {
        "moat": {"proposed_score": 10, "proposed_label": "Strong"},
        "ceo": {"proposed_score": 5, "proposed_label": "Decent"},
        "market_size": {"proposed_score": None, "proposed_label": "Missing"},
    }
    result = apply_alignment(proposals, {})
    assert result["status"] == "provisional", result
    assert result["provisional"] is True
    result2 = apply_alignment(proposals, {
        "moat": {"action": "accept"},
        "ceo": {"action": "adjust", "score": 10},
        "market_size": {"action": "missing"},
    })
    assert result2["status"] == "locked", result2
    assert result2["proposals"]["moat"]["aligned_score"] == 10
    assert result2["proposals"]["ceo"]["aligned_score"] == 10
    assert result2["proposals"]["ceo"]["alignment_status"] == "adjusted"
    assert result2["proposals"]["market_size"]["aligned_score"] is None
    assert result2["proposals"]["market_size"]["alignment_status"] == "missing"
    audit = {a["key"]: a for a in result2["audit_trail"]}
    assert audit["ceo"]["proposed_score"] == 5
    assert audit["ceo"]["aligned_score"] == 10


def test_alignment_invalid_adjust_stays_provisional():
    proposals = {"ceo": {"proposed_score": 5}}
    result = apply_alignment(proposals, {"ceo": {"action": "adjust", "score": 7}})
    assert result["status"] == "provisional", result
    assert result["proposals"]["ceo"]["alignment_status"] == "unaligned"


def test_ceo_founder_flat_margins_heavy_dilution_not_superstar():
    ceo = propose_ceo({
        "founder": True, "years_in_role": 12,
        "revenue_cagr_tenure_pct": 15.0, "margin_change_pp": 0.0,
        "return_vs_sp500_pp": 10.0, "insider_net_shares": 0,
        "dilution_note": "Heavy dilution from stock compensation.",
    })
    assert ceo["proposed_score"] != 10, ceo
    assert ceo["proposed_score"] == 5, ceo


def test_ceo_founder_strong_tenure_is_superstar():
    ceo = propose_ceo({
        "founder": True, "years_in_role": 12,
        "revenue_cagr_tenure_pct": 20.0, "margin_change_pp": 5.0,
        "return_vs_sp500_pp": 15.0, "insider_net_shares": 1000,
    })
    assert ceo["proposed_score"] == 10, ceo
    assert ceo["proposed_label"] == "Superstar", ceo


def test_moat_proposal_from_quant_proxies():
    q = _quality()
    moat = propose_moat(q, {"description": "Cloud platform with patents",
                            "industry": "Software"})
    assert moat["proposed_score"] in (0, 5, 10), moat
    assert moat["evidence"], moat
    assert moat["source"], moat
    assert moat["confidence"] in ("low", "medium", "high"), moat


def test_market_size_missing_is_not_guessed():
    m = propose_market_size({})
    assert m["proposed_score"] is None, m
    assert "tam" in m["missing"], m


def test_ondemand_review_order_and_provisional_banner():
    q = _quality()
    lt = _longterm(q, "strong", base=120.0)
    proposals = {
        "moat": {"proposed_score": 10, "proposed_label": "Strong"},
        "ceo": {"proposed_score": 5, "proposed_label": "Decent"},
        "market_size": {"proposed_score": None, "proposed_label": "Missing"},
    }
    review = build_ondemand_review(
        "TEST", 94.0, _trend(), {"decision": "wait", "entry_plan": {}},
        [], {"spy_above_200": True},
        {"days_away": 20, "status": "known"},
        q, lt, proposals,
    )
    assert review["short_term"]["trend"] == "up", review
    assert review["dca_decision"]["decision"] == "now", review
    assert review["alignment"]["provisional"] is True, review
    assert "provisional" in review["summary"].lower(), review
    assert set(["summary", "short_term", "longterm", "dca_decision",
                "proposals", "alignment"]) <= set(review.keys()), review


if __name__ == "__main__":
    import traceback

    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS {name}")
        except Exception:
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
