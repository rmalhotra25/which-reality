"""Ticker lookup plain-language card and DCA lane.

The DCA lane is separate from the timed verdict and from options.
NVDA on Oct 31 is the motivating case: price $204.64, 50-day
$221.68, 200-day $204.09, quality verified at composite 94.3,
DCF blocked for missing statements. Waiting for $221.68 would
mean paying $17.04 more for the same company, so a long-term
investor gets a DCA plan, not a timed wait. A DCA lane never
appears on a broken trend, with unverified quality, or when a
computed DCF says overvalued. Percentages round to one decimal.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.longterm_valuation import build_dca, build_longterm
from services.ticker_lookup import build_verdict


NVDA_SNAPSHOT = {
    "composite": 94.3, "label": "Compounder",
    "smoothed_rule_of_40": 95.3, "rev_cagr_3y_pct": 100.0,
    "fcf_margin_avg_3y_pct": 45.3, "operating_margin_pct": 65.2142628453736,
    "roic_pct": 102.387442503643, "ev_to_ebitda": 25.0, "fcf_yield_pct": 2.5,
}
FTNT_SNAPSHOT = {
    "composite": 71.0, "label": "Compounder",
    "smoothed_rule_of_40": 47.8, "rev_cagr_3y_pct": 15.5,
    "fcf_margin_avg_3y_pct": 32.3, "operating_margin_pct": 32.4,
    "roic_pct": 92.1, "ev_to_ebitda": 49.5, "fcf_yield_pct": 2.36,
}


def _setup(key, result, conditions=None):
    return {
        "setup_key": key,
        "setup_name": {"quality_pullback": "Quality Pullback",
                       "volume_breakout": "Volume Breakout"}.get(key, key),
        "rule_result": result, "status": "LIVE",
        "conditions": conditions or {}, "action": None,
        "suppressed_reason": None,
    }


def _fail_setups():
    return [
        _setup("quality_pullback", "fail",
               {"near_ma": False, "rsi_lt_55": False, "quiet_volume": False}),
        _setup("volume_breakout", "fail",
               {"above_55d_high": False, "vol_confirmed": False,
                "prior_high_55": 239.24}),
    ]


def _trend(price, ma50, ma200, ma50_dir="rising", ma200_dir="rising"):
    return {
        "price": price, "ma50": ma50, "ma200": ma200,
        "price_vs_ma50_pct": round((price - ma50) / ma50 * 100, 2) if ma50 else None,
        "price_vs_ma200_pct": round((price - ma200) / ma200 * 100, 2) if ma200 else None,
        "above_ma50": price > ma50 if ma50 else False,
        "above_ma200": price > ma200 if ma200 else False,
        "ma50_direction": ma50_dir, "ma200_direction": ma200_dir,
    }


def _quality():
    return {"composite": 80.0, "grade": "A",
            "components": {"trend": 80.0, "rsi": 80.0, "volume": 80.0},
            "inputs": {"rsi": 60.0, "volume_ratio_vs_20d": 1.0,
                       "iv_percentile": None},
            "note": "Display only."}


def _news():
    return {"status": "fresh_news", "source": "polygon_news", "error": None,
            "latest": {"title": "Analyst raises price target",
                       "published_date": "2026-10-30",
                       "publisher": "Analyst Wire", "url": None},
            "fresh_company_release": False,
            "note": "Fresh news shown as data, not counted as support."}


def _verdict(price, trend, fundamentals, statements=None, earnings_days=18,
             earnings_status="known", puts=None):
    return build_verdict(
        "TEST", price=price, setups=_fail_setups(),
        earnings={"status": earnings_status, "earnings_days": earnings_days,
                  "earnings_date": "2026-11-17"},
        spy_gate={"spy_above_200": True, "spy_vs_200ma_pct": 5.6,
                  "gate": "pass"},
        quality=_quality(), trend=trend,
        iv_percentile=None, news=_news(),
        chain_puts=puts or [], chain_calls=[],
        indicators={"prev_close": price, "prior_high_55": 239.24,
                    "rsi": 60.0, "volume": 1000, "vol20": 1000},
        fundamentals=fundamentals,
        longterm_statements=statements,
    )


def _nvda():
    trend = _trend(204.64, 221.68, 204.09)
    return _verdict(204.64, trend, NVDA_SNAPSHOT, statements=None)


def test_nvda_like_case_begin_dca_quality_based_not_timed_wait():
    v = _nvda()
    assert v["stock"]["decision"] == "wait"
    assert v["stock"]["label"] == "WAIT FOR ENTRY"
    lt = v["longterm"]
    assert lt["verdict"] == "blocked"
    assert lt["reason_code"] == "missing_statements"
    # BLOCKED text is printed once: reason once, notes empty.
    assert lt["notes"] == []
    assert "reported" in lt["reason"]
    assert "missing" in v["summary"]
    assert "market-closed" in lt["reason"] or "market-closed" in v["summary"]
    dca = v["dca"]
    assert dca is not None
    assert dca["label"] == "BEGIN DCA"
    assert dca["basis"] == "quality-based, valuation pending"
    assert "not valuation-backed" in dca["basis_note"] or "not a fair value" in dca["basis_note"] or "not valuation-backed" in v["summary"]
    # Thin range: no fake dip piece, because the 200-day is only
    # $0.55 below price and the midpoint is 0.13% below price.
    assert dca["dip_note"] is not None
    assert len(dca["pieces"]) == 2
    assert dca["pieces"][0]["price"] == 204.64
    assert dca["pieces"][1]["price"] == 221.68
    assert dca["invalidation_price"] == 204.09
    assert "204.09" in dca["pause_rule"]
    # Plain summary: better entry, not waiting for the higher price.
    assert "better entry" in v["summary"]
    assert "not waiting" in v["summary"]
    assert "221.68" in v["summary"]


def test_nvda_like_trigger_worded_as_recovery_not_pullback():
    v = _nvda()
    plan = v["stock"]["entry_plan"]
    assert plan["trigger_50d_wording"] == "recovery"
    assert "recovery" in plan["what_flips_to_buy"]
    assert v["stock"]["plain_explanation"] is not None
    assert "Trend not broken" in v["stock"]["plain_explanation"]
    assert "204.09" in v["stock"]["plain_explanation"]
    assert plan["buy_zone"] == [204.09, 221.68]


def test_price_above_50d_still_uses_pullback_wording():
    trend = _trend(200.0, 190.0, 180.0)
    v = _verdict(200.0, trend, {"status": "not_verified",
                                "note": "Not in snapshot."})
    plan = v["stock"]["entry_plan"]
    assert plan["trigger_50d_wording"] == "pullback"
    assert "pullback" in plan["what_flips_to_buy"].lower()


def test_trend_broken_shows_no_dca():
    trend = _trend(170.0, 180.0, 175.0, ma200_dir="falling")
    v = _verdict(170.0, trend, FTNT_SNAPSHOT, statements=None)
    assert v["stock"]["decision"] == "avoid"
    assert v["dca"] is None
    assert "no DCA plan" in v["summary"]


def test_quality_not_verified_shows_no_dca():
    trend = _trend(204.64, 221.68, 204.09)
    v = _verdict(204.64, trend, {"status": "not_verified",
                                 "note": "Not in snapshot."},
                 statements=None)
    assert v["longterm"]["verdict"] == "not_verified"
    assert v["dca"] is None


def test_dcf_overvalued_shows_no_dca_even_with_high_quality():
    # Computed DCF, all fair values below price: weak, overvalued.
    stm = {"revenue": 10000, "fcf": 1000, "shares_outstanding": 100,
           "beta": 1.0, "sector": "Technology", "revenue_growth_pct": 5.0,
           "operating_margin_pct": 32.4, "ev_to_ebitda": 49.5}
    trend = _trend(1000.0, 900.0, 800.0)
    v = _verdict(1000.0, trend, FTNT_SNAPSHOT, statements=stm)
    assert v["longterm"]["verdict"] == "weak"
    assert v["longterm"]["reason_code"] == "overvalued"
    assert v["dca"] is None


def test_valuation_backed_dca_with_distinct_dip_piece():
    stm = {"revenue": 100000, "fcf": 30000, "shares_outstanding": 1000,
           "beta": 1.0, "sector": "Technology", "revenue_growth_pct": 20.0,
           "operating_margin_pct": 32.4, "ev_to_ebitda": 49.5}
    trend = _trend(190.0, 200.0, 180.0)
    v = _verdict(190.0, trend, FTNT_SNAPSHOT, statements=stm)
    assert v["longterm"]["verdict"] == "strong"
    dca = v["dca"]
    assert dca is not None
    assert dca["basis"] == "valuation-backed"
    assert len(dca["pieces"]) == 3
    assert dca["pieces"][0]["price"] == 190.0
    assert dca["pieces"][1]["price"] == 185.0
    assert dca["pieces"][2]["price"] == 200.0
    assert dca["dip_note"] is None


def test_dca_does_not_change_put_or_call_gating():
    # WAIT with a qualifying put chain: put still sells, call
    # stays unavailable, DCA presence changes neither.
    puts = [{"strike": 190.0, "bid": 1.50, "ask": 1.60, "mid": 1.55,
             "dte": 21, "expiry": "2026-11-20", "delta": -0.30,
             "delta_abs": 0.30, "open_interest": 200}]
    trend = _trend(204.64, 221.68, 204.09)
    v = _verdict(204.64, trend, NVDA_SNAPSHOT, statements=None, puts=puts)
    assert v["dca"] is not None
    assert v["put"]["decision"] == "sell"
    assert v["call"]["decision"] == "not_available"
    assert v["call"]["reason_code"] == "stock_not_buy_now"


def test_dca_not_blocked_by_earnings_within_5_days_but_noted():
    trend = _trend(204.64, 221.68, 204.09)
    v = _verdict(204.64, trend, NVDA_SNAPSHOT, statements=None,
                 earnings_days=3)
    assert v["dca"] is not None
    assert "only piece before earnings" in v["dca"]["earnings_note"]


def test_dca_on_earnings_unknown_with_known_trend():
    trend = _trend(204.64, 221.68, 204.09)
    v = _verdict(204.64, trend, NVDA_SNAPSHOT, statements=None,
                 earnings_days=None, earnings_status="unknown")
    assert v["stock"]["decision"] == "cannot_judge"
    assert v["dca"] is not None
    assert "Keep early pieces small" in v["dca"]["earnings_note"]


def test_percentages_round_to_one_decimal():
    lt = build_longterm("NVDA", 204.64, {"status": "verified", **NVDA_SNAPSHOT},
                        statements=None)
    assert lt["quality"]["roic_pct"] == 102.4
    assert lt["quality"]["operating_margin_pct"] == 65.2
    assert lt["quality"]["rev_cagr_3y_pct"] == 100.0
    assert lt["quality"]["fcf_margin_avg_3y_pct"] == 45.3
    # Direct DCA helper: same eligibility rules, no verdict needed.
    dca = build_dca(204.64, _trend(204.64, 221.68, 204.09), lt, "wait",
                    earnings_days=18, earnings_known=True)
    assert dca is not None
    assert dca["discount_to_50d_pct"] == 8.3
