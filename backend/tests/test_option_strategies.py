"""Options Strategies section: best call, best put, straddle, iron condor.

Selection is model-ranked opportunity, not a prediction or a
guarantee. Ranking inputs are reported with the selected play,
so the reason it ranked first can be checked. Missing Greeks
are labelled Missing, never invented. No chain means the
section is unavailable, not fabricated strikes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.option_strategies import build_option_strategies


def _row(kind, strike, bid, ask, delta_abs, theta=0.05, gamma=0.02,
         vega=0.10, iv=30.0, oi=500, expiry="2026-11-20", dte=21):
    return {
        "strike": strike, "expiry": expiry, "dte": dte,
        "bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 2),
        "delta": delta_abs if kind == "call" else -delta_abs,
        "delta_abs": delta_abs, "theta_seller": theta,
        "gamma": gamma, "vega": vega, "iv_pct": iv,
        "open_interest": oi, "volume": 100,
    }


def _fixture():
    puts = [
        _row("put", 85, 0.8, 0.9, 0.15),
        _row("put", 90, 2.0, 2.2, 0.30),
        _row("put", 95, 4.0, 4.4, 0.45),
        _row("put", 100, 6.0, 6.4, 0.50),
    ]
    calls = [
        _row("call", 95, 7.0, 7.4, 0.65),
        _row("call", 100, 4.0, 4.4, 0.50),
        _row("call", 105, 2.0, 2.2, 0.30),
        _row("call", 110, 0.8, 0.9, 0.15),
    ]
    return puts, calls


def test_best_call_and_put_are_buys_with_breakeven_and_ranking():
    puts, calls = _fixture()
    result = build_option_strategies(100.0, puts, calls)
    assert result["available"] is True
    assert result["expiry"] == "2026-11-20"
    assert result["dte"] == 21
    for key in ("best_call", "best_put"):
        play = result[key]
        assert play["status"] == "ok"
        assert play["action"].startswith("Buy the")
        assert play["breakeven"] == round(
            play["strike"] + play["premium_per_share"], 2) \
            if key == "best_call" else round(
            play["strike"] - play["premium_per_share"], 2)
        assert play["max_loss_per_contract"] == round(play["premium_per_share"] * 100, 2)
        ranking = play["ranking"]
        assert ranking["score"] > 0
        assert ranking["delta_abs"] is not None
        assert "rough probability proxy" in ranking["delta_note"]
        assert ranking["spread_pct"] is not None
        assert ranking["open_interest"] is not None
        assert play["greeks"]["delta"] is not None


def test_straddle_breakevens_from_total_cost():
    puts, calls = _fixture()
    result = build_option_strategies(100.0, puts, calls)
    strad = result["straddle"]
    assert strad["status"] == "ok"
    assert strad["strike"] in (95, 100)
    total = strad["total_cost_per_share"]
    assert strad["lower_breakeven"] == round(strad["strike"] - total, 2)
    assert strad["upper_breakeven"] == round(strad["strike"] + total, 2)
    assert strad["total_cost_per_contract"] == round(total * 100, 2)
    assert strad["ranking"]["expected_move"] is not None


def test_iron_condor_credit_and_max_loss():
    puts, calls = _fixture()
    result = build_option_strategies(100.0, puts, calls)
    condor = result["iron_condor"]
    assert condor["status"] == "ok"
    assert condor["short_put_strike"] == 90
    assert condor["long_put_strike"] == 85
    assert condor["short_call_strike"] == 105
    assert condor["long_call_strike"] == 110
    credit = condor["net_credit_per_share"]
    # Short legs bid 2.0 each, wings ask 0.9 each: credit 2.2.
    assert credit == 2.2
    assert condor["net_credit_per_contract"] == 220.0
    # Width 5 on both sides, so max loss is 500 minus credit.
    assert condor["max_loss_per_contract"] == 280.0
    assert condor["lower_breakeven"] == round(90 - credit, 2)
    assert condor["upper_breakeven"] == round(105 + credit, 2)
    assert condor["return_on_risk_pct"] == round(220.0 / 280.0 * 100, 1)
    assert condor["ranking"]["short_put_delta_abs"] == 0.30
    assert condor["ranking"]["short_call_delta_abs"] == 0.30
    assert len(condor["ranking"]["legs"]) == 4


def test_missing_greeks_are_labelled_not_invented():
    puts, calls = _fixture()
    for row in puts + calls:
        row["gamma"] = None
        row["vega"] = None
    result = build_option_strategies(100.0, puts, calls)
    assert result["best_call"]["greeks"]["gamma"] is None
    assert result["best_call"]["greeks"]["vega"] is None
    assert result["straddle"]["greeks"]["gamma"] is None
    assert result["straddle"]["greeks"]["vega"] is None
    assert result["iron_condor"]["greeks"]["gamma"] is None


def test_expiry_rule_picks_nearest_to_21_dte():
    puts, calls = _fixture()
    far_puts = [_row("put", 90, 2.0, 2.2, 0.30, expiry="2026-12-20", dte=51)]
    far_calls = [_row("call", 105, 2.0, 2.2, 0.30, expiry="2026-12-20", dte=51)]
    result = build_option_strategies(100.0, puts + far_puts, calls + far_calls)
    assert result["expiry"] == "2026-11-20"
    assert result["dte"] == 21


def test_no_chain_means_unavailable_not_fabricated():
    result = build_option_strategies(100.0, [], [])
    assert result["available"] is False
    assert result["best_call"] is None
    assert result["straddle"] is None
    assert result["iron_condor"] is None
    assert result["reason"]


def test_wide_spread_and_thin_oi_rows_are_excluded():
    puts, calls = _fixture()
    bad_call = _row("call", 102, 1.0, 3.0, 0.45, oi=10)
    result = build_option_strategies(100.0, puts, calls + [bad_call])
    assert result["best_call"]["strike"] != 102
