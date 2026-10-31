"""Ticker lookup long-term lane, separate from the timing verdict.

The long-term lane never changes the timing verdict and never
changes put or call gating. GOOGL quality is verified in the
snapshot even when its timing verdict is AVOID. FTNT quality is
verified. META is not in the snapshot, so it is NOT VERIFIED, never
invented as strong. A DCF needs reported statements; without them
it is BLOCKED or NOT VERIFIED, never derived from market cap
divided by P/S. Negative FCF is BLOCKED, never floored away.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.longterm_valuation import build_longterm
from services.ticker_lookup import build_verdict


GOOGL_SNAPSHOT = {
    "composite": 59.0, "label": "Compounder",
    "smoothed_rule_of_40": 33.0, "rev_cagr_3y_pct": 12.5,
    "fcf_margin_avg_3y_pct": 20.5, "operating_margin_pct": 34.0,
    "roic_pct": 42.3, "ev_to_ebitda": 21.3, "fcf_yield_pct": 1.37,
}
FTNT_SNAPSHOT = {
    "composite": 71.0, "label": "Compounder",
    "smoothed_rule_of_40": 47.8, "rev_cagr_3y_pct": 15.5,
    "fcf_margin_avg_3y_pct": 32.3, "operating_margin_pct": 32.4,
    "roic_pct": 92.1, "ev_to_ebitda": 49.5, "fcf_yield_pct": 2.36,
}


def _statements(revenue, fcf, shares, price_unused=None, **kw):
    out = {
        "revenue": revenue, "fcf": fcf, "shares_outstanding": shares,
        "beta": 1.0, "sector": "Internet", "revenue_growth_pct": 12.5,
        "operating_margin_pct": 34.0, "ev_to_ebitda": 21.3,
    }
    out.update(kw)
    return out


def _setup(key, result, conditions=None, action=None):
    return {
        "setup_key": key,
        "setup_name": {"quality_pullback": "Quality Pullback",
                       "volume_breakout": "Volume Breakout"}.get(key, key),
        "rule_result": result, "status": "LIVE",
        "conditions": conditions or {}, "action": action,
        "suppressed_reason": None,
    }


def _fail_setups():
    return [
        _setup("quality_pullback", "fail",
               {"near_ma": False, "rsi_lt_55": False, "quiet_volume": False}),
        _setup("volume_breakout", "fail",
               {"above_55d_high": False, "vol_confirmed": False,
                "prior_high_55": 210.0}),
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


def _verdict(price=200.0, trend=None, fundamentals=None, statements=None):
    return build_verdict(
        "TEST", price=price, setups=_fail_setups(),
        earnings={"status": "known", "earnings_days": 18,
                  "earnings_date": "2026-11-17"},
        spy_gate={"spy_above_200": True, "spy_vs_200ma_pct": 5.6,
                  "gate": "pass"},
        quality=_quality(), trend=trend or _trend(price, 190.0, 180.0),
        iv_percentile=None, news=_news(),
        chain_puts=[], chain_calls=[],
        indicators={"prev_close": price, "prior_high_55": 210.0,
                    "rsi": 60.0, "volume": 1000, "vol20": 1000},
        fundamentals=fundamentals if fundamentals is not None else
        {"status": "not_verified", "note": "Not in snapshot."},
        longterm_statements=statements,
    )


def test_googl_quality_verified_even_when_timing_is_avoid():
    # Broken trend: below both averages, 200-day falling.
    trend = _trend(170.0, 180.0, 175.0, ma200_dir="falling")
    v = _verdict(price=170.0, trend=trend, fundamentals=GOOGL_SNAPSHOT,
                 statements=_statements(350000, 70000, 12000))
    assert v["stock"]["decision"] == "avoid"
    assert v["stock"]["label"] == "AVOID"
    lt = v["longterm"]
    assert lt["quality"]["status"] == "verified"
    assert lt["quality"]["composite"] == 59.0
    assert lt["quality"]["roic_pct"] == 42.3
    # Timing avoid must not force the long-term verdict to weak.
    assert lt["verdict"] in ("strong", "watch", "blocked")
    assert lt["verdict"] != "not_verified"


def test_ftnt_quality_verified():
    lt = build_longterm("FTNT", 100.0, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(6000, 2000, 250,
                                               sector="Technology",
                                               revenue_growth_pct=15.5,
                                               operating_margin_pct=32.4,
                                               ev_to_ebitda=49.5))
    assert lt["quality"]["status"] == "verified"
    assert lt["quality"]["composite"] == 71.0
    assert lt["quality"]["roic_pct"] == 92.1
    assert lt["dcf"] is not None
    assert lt["dcf"]["fair_value"]["bull"] > lt["dcf"]["fair_value"]["base"] \
        > lt["dcf"]["fair_value"]["bear"]


def test_meta_not_verified_not_invented_as_strong():
    lt = build_longterm("META", 600.0, {"status": "not_verified"},
                        statements=None)
    assert lt["verdict"] == "not_verified"
    assert lt["label"] == "NOT VERIFIED"
    assert lt["dcf"] is None
    v = _verdict(statements=None)
    assert v["longterm"]["verdict"] == "not_verified"


def test_blocked_on_negative_fcf():
    lt = build_longterm("TEST", 100.0, {"status": "verified", **GOOGL_SNAPSHOT},
                        statements=_statements(10000, -500, 100))
    assert lt["verdict"] == "blocked"
    assert lt["reason_code"] == "negative_fcf"
    assert lt["dcf"] is None


def test_blocked_on_missing_statements_with_verified_quality():
    lt = build_longterm("TEST", 100.0, {"status": "verified", **GOOGL_SNAPSHOT},
                        statements=None)
    assert lt["verdict"] == "blocked"
    assert lt["reason_code"] == "missing_statements"
    assert lt["dcf"] is None
    # No market-cap divided by P/S fallback is used: no fair value.
    assert "P/S" in lt["reason"] or "market cap" in lt["reason"]


def test_blocked_on_financial_sector():
    lt = build_longterm("TEST", 100.0, {"status": "verified", **GOOGL_SNAPSHOT},
                        statements=_statements(10000, 2000, 100,
                                               sector="Banks"))
    assert lt["verdict"] == "blocked"
    assert lt["reason_code"] == "financial_sector"


def test_bear_above_price_is_margin_of_safety_with_bridge():
    lt = build_longterm("TEST", 50.0, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(100000, 30000, 1000,
                                               revenue_growth_pct=20.0))
    assert lt["dcf"]["fair_value"]["bear"] > 50.0
    assert lt["verdict"] == "strong"
    assert lt["reason_code"] == "margin_of_safety"
    assert lt["bridge_line"] == "Long-term buy candidate, wait for entry"
    # Bridge entry prices are filled by build_verdict, not here.
    v = _verdict(price=50.0, trend=_trend(50.0, 45.0, 40.0),
                 fundamentals=FTNT_SNAPSHOT,
                 statements=_statements(100000, 30000, 1000,
                                        revenue_growth_pct=20.0))
    assert v["longterm"]["bridge_line"] == "Long-term buy candidate, wait for entry"
    assert v["longterm"]["bridge_entry"]["pullback_price"] == 45.0
    assert v["longterm"]["bridge_entry"]["invalidation_price"] == 40.0


def test_all_below_price_is_overvalued_even_with_high_quality():
    lt = build_longterm("TEST", 1000.0, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(10000, 1000, 100,
                                               revenue_growth_pct=5.0))
    assert lt["dcf"]["fair_value"]["bull"] < 1000.0
    assert lt["verdict"] == "weak"
    assert lt["reason_code"] == "overvalued"
    assert lt["bridge_line"] is None


def test_only_bull_above_price_is_watch():
    # Price set between base and bull fair values, found by scanning
    # the computed range rather than guessing a price in advance.
    lt_probe = build_longterm(
        "TEST", 100.0, {"status": "verified", **FTNT_SNAPSHOT},
        statements=_statements(10000, 2000, 100, revenue_growth_pct=10.0))
    base = lt_probe["dcf"]["fair_value"]["base"]
    bull = lt_probe["dcf"]["fair_value"]["bull"]
    assert bull > base
    mid = (base + bull) / 2
    lt = build_longterm("TEST", mid, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(10000, 2000, 100,
                                               revenue_growth_pct=10.0))
    assert lt["verdict"] == "watch"
    assert lt["reason_code"] == "fairly_valued"


def test_timing_avoid_does_not_change_longterm_or_option_gating():
    trend = _trend(170.0, 180.0, 175.0, ma200_dir="falling")
    v = _verdict(price=170.0, trend=trend, fundamentals=FTNT_SNAPSHOT,
                 statements=_statements(100000, 30000, 1000,
                                        revenue_growth_pct=20.0))
    # Long-term strong, timing avoid, options still gated off.
    assert v["longterm"]["verdict"] == "strong"
    assert v["stock"]["decision"] == "avoid"
    assert v["put"]["decision"] == "not_available"
    assert v["put"]["reason_code"] == "stock_not_buy_now"
    assert v["call"]["decision"] == "not_available"
    assert v["call"]["reason_code"] == "stock_not_buy_now"


def test_wacc_fallback_is_stated_and_live_rate_is_used():
    lt = build_longterm("TEST", 100.0, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(10000, 2000, 100))
    assert lt["wacc"]["risk_free_source"] == "fallback_hardcoded_4.5pct"
    assert lt["wacc"]["risk_free_pct"] == 4.5
    lt_live = build_longterm(
        "TEST", 100.0, {"status": "verified", **FTNT_SNAPSHOT},
        statements=_statements(10000, 2000, 100),
        risk_free_rate=0.05)
    assert lt_live["wacc"]["risk_free_source"] == "live_10y_yield_supplied"
    assert lt_live["wacc"]["risk_free_pct"] == 5.0
    assert lt_live["wacc"]["wacc_pct"] != lt["wacc"]["wacc_pct"] \
        or lt_live["dcf"]["fair_value"] != lt["dcf"]["fair_value"]


def test_exit_multiple_check_present_or_flagged_unavailable():
    lt = build_longterm("TEST", 100.0, {"status": "verified", **FTNT_SNAPSHOT},
                        statements=_statements(10000, 2000, 100))
    check = lt["dcf"]["exit_multiple_check"]
    assert check["method"] == "industry_exit_multiple_ev_ebitda"
    assert check["fair_value"] is not None
    assert check["gordon_fair_value"] == lt["dcf"]["fair_value"]["base"]
    lt_no_ev = build_longterm(
        "TEST", 100.0, {"status": "not_verified"},
        statements=_statements(10000, 2000, 100, operating_margin_pct=None,
                               ev_to_ebitda=None))
    assert lt_no_ev["dcf"]["exit_multiple_check"]["fair_value"] is None
