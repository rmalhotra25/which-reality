"""Tests for Today's Book sizing and pricing rules.

Quant decides, AI explains. These tests pin the non-negotiable rules:
a mid or a zero bid/ask is never a tradable price, a seller collects
the bid less half the spread, sizing follows the portfolio simulator
caps, and SHADOW items are never sized by rank_and_size (the router
only passes LIVE candidates; these tests pin the sizing side).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.today_book import (
    build_risk_bar,
    drawdown_pct,
    net_buy_cost,
    net_sell_premium,
    rank_and_size,
    risk_budget_dollars,
    size_contracts,
)


def _settings(**over):
    s = {
        "account_equity": 100000.0,
        "peak_equity": 100000.0,
        "risk_pct": 1.0,
        "max_heat_pct": 10.0,
        "max_positions": 10,
        "max_position_pct": 10.0,
    }
    s.update(over)
    return s


def _put(ticker="MSFT", strike=410.0, premium=2.00, **over):
    c = {
        "kind": "wheel",
        "ticker": ticker,
        "status": "LIVE",
        "strike": strike,
        "expiry": "2026-12-18",
        "dte": 35,
        "premium_net_per_share": premium,
        "premium_net_per_contract": premium * 100,
        "max_loss_per_contract": (strike - premium) * 100,
        "notional_per_contract": strike * 100,
        "quant_score": 80.0,
    }
    c.update(over)
    return c


# --- Pricing: bid, never mid, never last trade -------------------------

def test_sell_premium_is_bid_less_half_spread():
    premium, tradable, reason, spread_pct = net_sell_premium(2.00, 2.20)
    assert tradable and reason is None
    assert premium == 1.90
    assert spread_pct == 9.5


def test_zero_bid_is_not_a_tradable_price():
    premium, tradable, reason, _ = net_sell_premium(0.0, 0.0)
    assert not tradable and premium is None
    assert reason == "no_executable_bid"


def test_zero_ask_is_not_a_tradable_price():
    premium, tradable, reason, _ = net_sell_premium(2.00, 0.0)
    assert not tradable and premium is None
    assert reason == "no_executable_ask"


def test_wide_spread_is_untradable():
    premium, tradable, reason, spread_pct = net_sell_premium(1.00, 1.60)
    assert not tradable and premium is None
    assert reason == "spread_too_wide"
    assert spread_pct == 46.2


def test_buy_cost_is_ask_plus_half_spread():
    cost, tradable, reason, _ = net_buy_cost(5.20, 5.00)
    assert tradable and reason is None
    assert cost == 5.30


def test_buy_with_zero_bid_is_not_tradable():
    cost, tradable, reason, _ = net_buy_cost(5.20, 0.0)
    assert not tradable and cost is None


# --- Sizing: simulator caps --------------------------------------------

def test_one_percent_risk_budget_sizes_a_put():
    # $1,000 budget / $40,800 max loss per contract = 0 contracts:
    # a $410 strike put is too big for a $100k account at 1% risk.
    contracts, reason = size_contracts(40800.0, 1000.0, 41000.0, 100000.0, 10.0)
    assert contracts == 0 and reason == "risk_budget_too_small"


def test_small_max_loss_sizes_multiple_contracts():
    contracts, reason = size_contracts(500.0, 1000.0, 4000.0, 100000.0, 10.0)
    assert contracts == 2 and reason is None


def test_single_position_cap_binds():
    # Budget allows 10 contracts, but 10% of equity caps notional at
    # $10,000, so only 1 contract of $10,000 notional fits.
    contracts, reason = size_contracts(100.0, 1000.0, 10000.0, 100000.0, 10.0)
    assert contracts == 1 and reason is None


def test_drawdown_halves_then_pauses_risk_budget():
    assert risk_budget_dollars(100000.0, 1.0, 0.0) == 1000.0
    assert risk_budget_dollars(100000.0, 1.0, 10.0) == 500.0
    assert risk_budget_dollars(100000.0, 1.0, 15.0) == 0.0
    assert drawdown_pct(85000.0, 100000.0) == 15.0


def test_rank_and_size_blocks_when_heat_cap_would_breach():
    # Current heat $9,000 of a $10,000 cap. Each candidate risks
    # $1,000 (2 contracts x $500 max loss), so the first fits exactly
    # and the second breaches the cap.
    cands = [
        _put("AAA", strike=10.0, premium=5.00),
        _put("BBB", strike=10.0, premium=5.00),
    ]
    items, blocked = rank_and_size(cands, _settings(), 9000.0, 0)
    assert len(items) == 1
    assert items[0]["risk_dollars"] == 1000.0
    assert len(blocked) == 1
    assert blocked[0]["blocked_reason"] == "heat_cap"


def test_rank_and_size_blocks_on_drawdown_pause():
    cands = [_put("AAA", strike=100.0, premium=5.00)]
    items, blocked = rank_and_size(
        cands, _settings(account_equity=85000.0, peak_equity=100000.0), 0.0, 0)
    assert items == []
    assert blocked[0]["blocked_reason"] == "drawdown_pause"


def test_rank_and_size_blocks_on_concurrency_cap():
    cands = [_put("AAA", strike=100.0, premium=5.00)]
    items, blocked = rank_and_size(cands, _settings(max_positions=2), 0.0, 2)
    assert items == []
    assert blocked[0]["blocked_reason"] == "concurrency_cap"


def test_ranked_by_premium_per_dollar_at_risk():
    cheap = _put("AAA", strike=10.0, premium=0.10)   # 10 / 990
    rich = _put("BBB", strike=10.0, premium=5.00)    # 500 / 500
    items, _ = rank_and_size([cheap, rich], _settings(), 0.0, 0)
    assert [i["ticker"] for i in items] == ["BBB", "AAA"]


def test_covered_call_sized_by_shares_not_risk_budget():
    cc = {
        "kind": "covered_call", "ticker": "MSFT", "status": "LIVE",
        "strike": 450.0, "expiry": "2026-12-18", "dte": 35,
        "premium_net_per_share": 2.00, "premium_net_per_contract": 200.0,
        "max_loss_per_contract": 0.0, "notional_per_contract": 0.0,
        "current_price": 440.0, "contracts_fixed": 2,
    }
    items, blocked = rank_and_size([cc], _settings(), 0.0, 0)
    assert blocked == []
    assert items[0]["contracts"] == 2
    assert items[0]["risk_dollars"] == 0.0
    assert items[0]["premium_net_total"] == 400.0


def test_risk_bar_reports_heat_capacity_and_brake():
    bar = build_risk_bar(_settings(), 2000.0, 3)
    assert bar["account_equity"] == 100000.0
    assert bar["current_heat_dollars"] == 2000.0
    assert bar["current_heat_pct"] == 2.0
    assert bar["remaining_capacity_dollars"] == 8000.0
    assert bar["drawdown_brake"] == "none"
    bar2 = build_risk_bar(_settings(account_equity=88000.0), 2000.0, 3)
    assert bar2["drawdown_pct"] == 12.0
    assert bar2["drawdown_brake"] == "reduced"


# --- Wheel sizing by premium at risk ------------------------------------
# A wheel put is sized by the premium collected per contract, not by
# the assignment worst case. The worst case is still reported as
# max_loss_per_contract and as capital_at_risk; it is not the sizing
# risk. A $505 MSFT put collecting $635 was blocked before this change
# (max loss $49,865 against a $1,000 budget) and sizes to 1 contract
# after it.

def _wheel_put(ticker, strike, premium, **over):
    c = _put(ticker, strike=strike, premium=premium)
    c["risk_per_contract"] = premium * 100
    c["risk_measure"] = "premium_at_risk"
    c.update(over)
    return c


def test_wheel_sized_by_premium_at_risk():
    cands = [_wheel_put("MSFT", 505.0, 6.35)]
    items, blocked = rank_and_size(cands, _settings(), 0.0, 0)
    assert blocked == []
    assert items[0]["contracts"] == 1
    assert items[0]["risk_dollars"] == 635.0
    assert items[0]["risk_measure"] == "premium_at_risk"
    # Assignment worst case and cash needed are still shown honestly.
    assert items[0]["max_loss_per_contract"] == 49865.0
    assert items[0]["capital_at_risk"] == 50500.0


def test_wheel_still_blocked_when_premium_exceeds_budget():
    # AMD $530 put, $23.95 premium: $2,395 of premium at risk is more
    # than the $1,000 budget, so it stays blocked.
    cands = [_wheel_put("AMD", 530.0, 23.95)]
    items, blocked = rank_and_size(cands, _settings(), 0.0, 0)
    assert items == []
    assert blocked[0]["blocked_reason"] == "risk_budget_too_small"


def test_wheel_heat_accumulates_premium_risk():
    cands = [
        _wheel_put("QCOM", 175.0, 6.60),
        _wheel_put("PANW", 365.0, 7.70),
    ]
    items, blocked = rank_and_size(cands, _settings(), 9000.0, 0)
    # First risks $660 of premium, fitting exactly under the $10,000
    # heat cap; the second would add $770 and breach it.
    assert len(items) == 1
    assert items[0]["risk_dollars"] == 660.0
    assert len(blocked) == 1
    assert blocked[0]["blocked_reason"] == "heat_cap"


def test_non_wheel_still_sized_by_max_loss():
    # A bought setup-alert put: sizing risk is the max loss ($1,000),
    # not the premium paid ($4,000). The single-position cap still
    # uses its notional.
    cands = [{
        "kind": "setup_alert", "ticker": "XYZ", "status": "LIVE",
        "contract_type": "PUT", "strike": 50.0, "expiry": "2026-12-18",
        "premium_net_per_share": 40.0, "premium_net_per_contract": 4000.0,
        "max_loss_per_contract": 1000.0, "notional_per_contract": 5000.0,
        "quant_score": 80.0,
    }]
    items, blocked = rank_and_size(cands, _settings(), 0.0, 0)
    assert blocked == []
    assert items[0]["contracts"] == 1
    assert items[0]["risk_dollars"] == 1000.0


def test_size_contracts_risk_cap_basis():
    # Premium-at-risk sizing with the single-position cap on risk
    # dollars: 2 contracts at $400 risk each, cap $10,000 / $400 = 25.
    contracts, reason = size_contracts(
        50000.0, 1000.0, 50000.0, 100000.0, 10.0,
        risk_per_contract=400.0, cap_basis="risk")
    assert contracts == 2 and reason is None
    # With a $20,000 budget the risk cap binds: 33 by budget, 16 by cap.
    contracts, reason = size_contracts(
        50000.0, 20000.0, 50000.0, 100000.0, 10.0,
        risk_per_contract=600.0, cap_basis="risk")
    assert contracts == 16 and reason is None


def test_size_contracts_notional_cap_still_binds_without_risk_basis():
    # Small max loss but huge notional: budget allows 2 contracts,
    # the 10% notional cap allows 0.
    contracts, reason = size_contracts(500.0, 1000.0, 50000.0, 100000.0, 10.0)
    assert contracts == 0 and reason == "single_position_cap"
