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
