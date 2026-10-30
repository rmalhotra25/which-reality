"""Tiered ticker lookup verdicts: BUY NOW, WAIT, AVOID, CANNOT JUDGE.

BUY NOW keeps the strict old rule. WAIT is a good trend with no
trigger today, with a trigger price and an invalidation. AVOID is a
broken trend. CANNOT JUDGE means a gate or trend input is missing,
so no stock judgment is claimed. The put is decoupled from BUY NOW
only on WAIT, with a 4% cushion floor; the call stays BUY NOW only.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ticker_lookup import build_verdict


def _setup(key, result, conditions=None, action=None):
    return {
        "setup_key": key,
        "setup_name": {"quality_pullback": "Quality Pullback",
                       "volume_breakout": "Volume Breakout"}.get(key, key),
        "rule_result": result,
        "status": "LIVE",
        "conditions": conditions or {},
        "action": action,
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


def _trend(price=200.0, ma50=190.0, ma200=180.0, ma50_dir="rising",
           ma200_dir="rising"):
    return {
        "price": price, "ma50": ma50, "ma200": ma200,
        "price_vs_ma50_pct": round((price - ma50) / ma50 * 100, 2) if ma50 else None,
        "price_vs_ma200_pct": round((price - ma200) / ma200 * 100, 2) if ma200 else None,
        "above_ma50": price > ma50 if ma50 else False,
        "above_ma200": price > ma200 if ma200 else False,
        "ma50_direction": ma50_dir, "ma200_direction": ma200_dir,
    }


def _quality(rsi=60.0, vol_ratio=1.0):
    return {"composite": 80.0, "grade": "A",
            "components": {"trend": 80.0, "rsi": 80.0, "volume": 80.0},
            "inputs": {"rsi": rsi, "volume_ratio_vs_20d": vol_ratio,
                       "iv_percentile": None},
            "note": "Display only."}


def _news(title="Analyst raises price target"):
    return {"status": "fresh_news", "source": "polygon_news", "error": None,
            "latest": {"title": title, "published_date": "2026-10-30",
                       "publisher": "Analyst Wire", "url": None},
            "fresh_company_release": False,
            "note": "Fresh news shown as data, not counted as support."}


def _verdict(price=200.0, setups=None, earnings_days=18,
             earnings_status="known", spy=True, trend=None, news=None,
             puts=None, calls=None, indicators=None, fundamentals=None,
             vol_ratio=1.0):
    return build_verdict(
        "TEST", price=price, setups=setups if setups is not None else _fail_setups(),
        earnings={"status": earnings_status, "earnings_days": earnings_days,
                  "earnings_date": "2026-11-17"},
        spy_gate={"spy_above_200": spy, "spy_vs_200ma_pct": 5.6, "gate": "pass"},
        quality=_quality(vol_ratio=vol_ratio), trend=trend or _trend(price=price),
        iv_percentile=None, news=news or _news(),
        chain_puts=puts or [], chain_calls=calls or [],
        indicators=indicators or {"prev_close": 200.0, "prior_high_55": 210.0,
                                  "rsi": 60.0, "volume": 1000, "vol20": 1000},
        fundamentals=fundamentals if fundamentals is not None else
        {"status": "not_verified", "note": "Not in snapshot."},
    )


def _put(strike, bid=1.50, ask=1.60, dte=21, oi=200):
    return [{"strike": strike, "bid": bid, "ask": ask, "mid": 1.55,
             "dte": dte, "expiry": "2026-11-20", "delta": -0.30,
             "delta_abs": 0.30, "open_interest": oi}]


def test_buy_now_unchanged_and_strict():
    action = {"entry_price": 200.0, "invalidation_price": 190.0,
              "target_price": 220.0, "exit_rule": "close below invalidation"}
    setups = [_setup("quality_pullback", "pass", {}, action),
              _setup("volume_breakout", "fail", {})]
    v = _verdict(setups=setups, puts=_put(190.0),
                 calls=[{"strike": 205.0, "ask": 3.0, "mid": 2.9, "dte": 21,
                         "expiry": "2026-11-20"}])
    assert v["stock"]["decision"] == "buy"
    assert v["stock"]["tier"] == "buy_now"
    assert v["stock"]["label"] == "BUY NOW"
    assert v["put"]["decision"] == "sell"
    assert v["call"]["decision"] == "buy"


def test_wait_trend_up_no_setup_with_entry_plan_and_put():
    v = _verdict(puts=_put(190.0))
    stock = v["stock"]
    assert stock["decision"] == "wait"
    assert stock["tier"] == "wait_for_entry"
    assert stock["label"] == "WAIT FOR ENTRY"
    plan = stock["entry_plan"]
    assert plan["pullback_price"] == 190.0
    assert plan["breakout_price"] == 210.0
    assert plan["invalidation_price"] == 180.0
    assert plan["buy_zone"] == [180.0, 190.0]
    assert "pullback" in plan["what_flips_to_buy"].lower()
    assert v["put"]["decision"] == "sell"
    assert v["put"]["cushion_pct"] == 5.0
    assert v["call"]["decision"] == "not_available"
    assert v["call"]["reason_code"] == "stock_not_buy_now"


def test_wait_put_blocked_on_thin_cushion():
    v = _verdict(puts=_put(198.0))
    assert v["stock"]["decision"] == "wait"
    assert v["put"]["decision"] == "dont_sell"
    assert v["put"]["reason_code"] == "cushion_too_thin"
    assert v["put"]["cushion_pct"] == 1.0


def test_cannot_judge_on_earnings_unknown():
    v = _verdict(earnings_days=None, earnings_status="earnings_unknown",
                 puts=_put(190.0))
    assert v["stock"]["decision"] == "cannot_judge"
    assert v["stock"]["label"] == "CANNOT JUDGE"
    assert v["put"]["decision"] == "not_available"
    assert v["put"]["reason_code"] == "earnings_unknown"
    assert v["call"]["decision"] == "not_available"


def test_avoid_on_broken_trend():
    trend = _trend(price=170.0, ma50=180.0, ma200=175.0, ma200_dir="falling")
    v = _verdict(price=170.0, trend=trend, puts=_put(160.0))
    assert v["stock"]["decision"] == "avoid"
    assert v["stock"]["label"] == "AVOID"
    assert v["put"]["decision"] == "not_available"
    assert v["call"]["decision"] == "not_available"


def test_wait_on_earnings_in_three_days_no_put():
    v = _verdict(earnings_days=3, puts=_put(190.0))
    assert v["stock"]["decision"] == "wait"
    assert "3 day" in v["stock"]["reasons"][0]
    assert v["put"]["decision"] == "not_available"
    assert v["put"]["reason_code"] == "earnings_block"


def test_wait_on_spy_below_is_not_avoid():
    v = _verdict(spy=False, puts=_put(190.0))
    assert v["stock"]["decision"] == "wait"
    assert v["put"]["decision"] == "not_available"
    assert v["put"]["reason_code"] == "spy_block"


def test_news_classification_earnings_vs_analyst():
    v = _verdict(news=_news("Company reports earnings and raises guidance"))
    assert v["stock"]["entry_plan"]["news_context"]["category"] == "earnings_guidance"
    v2 = _verdict(news=_news("Analyst raises price target"))
    assert v2["stock"]["entry_plan"]["news_context"]["category"] == "analyst"


def test_entry_plan_fundamentals_verified_only_when_supplied():
    fund = {"composite": 94.3, "label": "Compounder",
            "smoothed_rule_of_40": 95.3, "rev_cagr_3y_pct": 100.0,
            "fcf_margin_avg_3y_pct": 45.3, "operating_margin_pct": 65.2}
    v = _verdict(fundamentals=fund)
    assert v["stock"]["entry_plan"]["fundamentals"]["status"] == "verified"
    assert v["stock"]["entry_plan"]["fundamentals"]["composite"] == 94.3
    v2 = _verdict()
    assert v2["stock"]["entry_plan"]["fundamentals"]["status"] == "not_verified"


def test_extended_and_heavy_drop_notes():
    trend = _trend(price=210.0, ma50=190.0, ma200=180.0)
    v = _verdict(price=210.0, trend=trend, vol_ratio=2.0,
                 indicators={"prev_close": 220.0, "prior_high_55": 215.0,
                             "rsi": 60.0, "volume": 2000, "vol20": 1000})
    notes = " ".join(v["stock"]["entry_plan"]["notes"])
    assert "Extended" in notes
    assert "Heavy volume" in notes
