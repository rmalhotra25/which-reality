"""
Backtest harness regression tests: drawdown date-ordering, calendar
regimes, portfolio simulator, and random-entry baseline.

Run from backend/ dir:
    pytest tests/test_backtest_harness.py -v

No network access: all tests use hardcoded trades and synthetic OHLCV
built in-memory. These tests verify mechanics only; their numbers are
NOT backtest results.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from services.backtest_harness import (
    SimulatorParams,
    Trade,
    _baseline_summary,
    _calendar_regime,
    _compute_stats_for_trades,
    _max_drawdown,
    _random_baseline_trades,
    _split_trades,
    simulate_portfolio,
)


def _trade(entry, exit_, pnl, ticker="AAA", risk_pct=None, entry_price=100.0):
    exit_price = entry_price * (1 + pnl / 100)
    return Trade(
        ticker=ticker,
        signal_date=entry - timedelta(days=1),
        entry_date=entry,
        entry_price=entry_price,
        exit_date=exit_,
        exit_price=exit_price,
        exit_reason="time",
        regime_calendar=_calendar_regime(entry),
        regime_spy_ma="above_200",
        pnl_pct=pnl,
        risk_pct=risk_pct,
    )


# ---------------------------------------------------------------------------
# Calendar regimes
# ---------------------------------------------------------------------------

def test_calendar_regime_buckets():
    assert _calendar_regime(date(2019, 6, 3)) == "pre_2022"
    assert _calendar_regime(date(2021, 12, 31)) == "pre_2022"
    assert _calendar_regime(date(2022, 1, 1)) == "bear_2022"
    assert _calendar_regime(date(2022, 12, 31)) == "bear_2022"
    assert _calendar_regime(date(2023, 1, 1)) == "bull_2023_2024"
    assert _calendar_regime(date(2024, 12, 31)) == "bull_2023_2024"
    assert _calendar_regime(date(2025, 1, 1)) == "recent_2025"
    assert _calendar_regime(date(2026, 10, 26)) == "recent_2025"


def test_split_trades_includes_pre_2022_bucket():
    trades = [
        _trade(date(2020, 3, 2), date(2020, 3, 20), 5.0),
        _trade(date(2022, 6, 1), date(2022, 6, 10), -2.0),
        _trade(date(2025, 2, 3), date(2025, 2, 12), 3.0),
    ]
    splits = _split_trades(trades)
    assert splits["regime_pre_2022"]["trade_count"] == 1
    assert splits["regime_bear_2022"]["trade_count"] == 1
    assert splits["regime_recent_2025"]["trade_count"] == 1
    assert splits["regime_bull_2023_2024"]["trade_count"] == 0


# ---------------------------------------------------------------------------
# Drawdown is date-ordered, not ticker-ordered
# ---------------------------------------------------------------------------

def test_max_drawdown_ignores_input_order():
    # Same trades in ticker order (B before A) and date order must give
    # the same drawdown once _compute_stats_for_trades sorts by date.
    d = date(2024, 1, 2)
    ticker_order = [
        _trade(d + timedelta(days=30), d + timedelta(days=40), -8.0, ticker="ZZZ"),
        _trade(d, d + timedelta(days=10), 10.0, ticker="AAA"),
    ]
    date_order = list(reversed(ticker_order))
    assert _compute_stats_for_trades(ticker_order) == _compute_stats_for_trades(date_order)
    stats = _compute_stats_for_trades(ticker_order)
    # Equity: 100 -> 110 -> 101.20; peak 110, trough 101.20, DD 8.00%.
    assert abs(stats["max_drawdown_pct"] - 8.00) < 0.01


def test_max_drawdown_matches_hand_computation():
    # Returns +4, -2, +6, -1 in date order: peaks 104, 108.04; DD 2.00%.
    assert abs(_max_drawdown([4.0, -2.0, 6.0, -1.0]) - 2.00) < 0.01
    assert _max_drawdown([]) == 0.0


# ---------------------------------------------------------------------------
# Portfolio simulator
# ---------------------------------------------------------------------------

def _sim_trades():
    d = date(2024, 1, 2)
    return [
        _trade(d, d + timedelta(days=5), 10.0, ticker="AAA", risk_pct=5.0),
        _trade(d, d + timedelta(days=5), -5.0, ticker="BBB", risk_pct=5.0),
        _trade(d + timedelta(days=10), d + timedelta(days=15), 10.0, ticker="CCC", risk_pct=5.0),
    ]


def test_simulator_known_numbers():
    # Three trades, 1% risk each, 5% stop distance: each position is
    # 20% of equity capped at the 10% notional cap, so each risks 0.5%.
    # First two exit the same day: winners gain 10% on $10,000 = +$1,000,
    # loser loses 5% on $10,000 = -$500, so equity is $100,500 when the
    # third trade enters. Its capped $10,050 position gains 10% = +$1,005.
    # Final equity $101,505; profit factor 2005 / 500 = 4.01.
    sim = simulate_portfolio(_sim_trades())
    assert sim["trades_taken"] == 3
    assert sim["trades_skipped"] == 0
    assert sim["final_equity"] == pytest.approx(101505.0)
    assert sim["total_return_pct"] == pytest.approx(1.505, abs=0.01)
    assert sim["max_concurrent_positions"] == 2
    assert sim["avg_duration_days"] == pytest.approx(5.0)
    # Expectancy is the mean pnl_pct of taken trades: (10 - 5 + 10) / 3.
    assert sim["expectancy_pct"] == pytest.approx(5.0)
    # Profit factor in dollars: 2005 / 500 = 4.01.
    assert sim["profit_factor"] == pytest.approx(4.01)


def test_simulator_same_day_trades_free_slots():
    # Same-day trades (entry_date == exit_date) exit after their entry,
    # so the slot and cash free the same day. Twelve of them in a row
    # with max_positions=2 must all be taken; if the exit ran before the
    # entry, the first two would lock their slots forever and only 2
    # would ever be taken.
    d = date(2024, 1, 2)
    trades = [
        _trade(d + timedelta(days=i), d + timedelta(days=i), 1.0,
               ticker=f"T{i:02d}", risk_pct=5.0)
        for i in range(12)
    ]
    sim = simulate_portfolio(trades, SimulatorParams(max_positions=2))
    assert sim["trades_taken"] == 12
    assert sim["trades_skipped"] == 0
    # Each +1% trade gains ~1% on a 10%-of-equity position, compounding
    # slightly as equity grows: about +$1,207 total.
    assert sim["final_equity"] == pytest.approx(101206.62, abs=1.0)


def test_simulator_same_day_trades_do_not_lock_cash():
    # A same-day loser followed by months of later trades: the later
    # trades must still be taken, proving the loser's cash was freed.
    d = date(2024, 1, 2)
    trades = [_trade(d, d, -5.0, ticker="AAA", risk_pct=5.0)]
    trades += [
        _trade(d + timedelta(days=30 + i * 20),
               d + timedelta(days=35 + i * 20), 1.0,
               ticker=f"T{i:02d}", risk_pct=5.0)
        for i in range(20)
    ]
    sim = simulate_portfolio(trades, SimulatorParams(max_positions=10))
    assert sim["trades_taken"] == 21
    assert sim["max_concurrent_positions"] >= 1


def test_simulator_empty_input_returns_zeros():
    sim = simulate_portfolio([])
    assert sim["trades_taken"] == 0
    assert sim["final_equity"] == pytest.approx(100000.0)
    assert sim["max_drawdown_pct"] == 0.0
    assert sim["cagr_pct"] == 0.0


def test_simulator_max_positions_cap():
    d = date(2024, 1, 2)
    trades = [
        _trade(d, d + timedelta(days=30), 1.0, ticker=f"T{i:02d}", risk_pct=5.0)
        for i in range(15)
    ]
    sim = simulate_portfolio(trades, SimulatorParams(max_positions=10))
    assert sim["trades_taken"] == 10
    assert sim["skipped_max_positions"] == 5
    assert sim["max_concurrent_positions"] == 10


def test_simulator_heat_cap():
    d = date(2024, 1, 2)
    # Each trade risks 1% of equity with a 20% stop distance, so sizing
    # is not notional-capped: risk_dollars is $1,000 per trade. A 2%
    # heat cap allows only 2 concurrent trades.
    trades = [
        _trade(d, d + timedelta(days=30), 1.0, ticker=f"T{i:02d}", risk_pct=20.0)
        for i in range(6)
    ]
    sim = simulate_portfolio(trades, SimulatorParams(max_heat_pct=2.0))
    assert sim["trades_taken"] == 2
    assert sim["skipped_heat"] == 4


def test_simulator_pause_breaker():
    d = date(2024, 1, 2)
    # First trade loses 40% on a 10% capped position = -$4,000, a 4%
    # equity drawdown. With a 3% pause threshold, later entries pause
    # until equity recovers, which it never does here.
    trades = [
        _trade(d, d + timedelta(days=5), -40.0, ticker="AAA", risk_pct=5.0),
        _trade(d + timedelta(days=10), d + timedelta(days=15), 10.0, ticker="BBB", risk_pct=5.0),
    ]
    sim = simulate_portfolio(
        trades, SimulatorParams(pause_dd_pct=3.0, reduce_dd_pct=2.0))
    assert sim["trades_taken"] == 1
    assert sim["skipped_paused"] == 1
    assert sim["max_drawdown_pct"] == pytest.approx(4.0)


def test_simulator_fallback_sizing_without_stop():
    # No risk_pct: position sized at the 10% notional cap. A +10% trade
    # on $10,000 notional gains $1,000.
    d = date(2024, 1, 2)
    sim = simulate_portfolio([_trade(d, d + timedelta(days=5), 10.0)])
    assert sim["trades_taken"] == 1
    assert sim["final_equity"] == pytest.approx(101000.0)


def test_simulator_calmar_and_recovery():
    # Single losing trade: -10% on a 10% capped position = -$1,000,
    # a 1% drawdown. CAGR is negative, Calmar negative, recovery -1.00.
    d = date(2024, 1, 2)
    sim = simulate_portfolio([_trade(d, d + timedelta(days=365), -10.0)])
    assert sim["max_drawdown_pct"] == pytest.approx(1.0)
    assert sim["recovery_factor"] == pytest.approx(-1.0)
    assert sim["calmar_ratio"] < 0


# ---------------------------------------------------------------------------
# Random-entry baseline
# ---------------------------------------------------------------------------

def _flat_history(ticker, start="2019-01-01", periods=2000):
    rng = np.random.default_rng(7)
    dates = pd.bdate_range(start=start, periods=periods)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, periods)))
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.002,
            "Low": closes * 0.998,
            "Close": closes,
            "Volume": np.full(periods, 1_000_000.0),
        },
        index=dates,
    )


def test_random_baseline_same_count_and_holding_periods():
    data = {"AAA": _flat_history("AAA"), "BBB": _flat_history("BBB")}
    d = date(2024, 1, 2)
    ref = [
        _trade(d, d + timedelta(days=9), 2.0, ticker="AAA"),
        _trade(d + timedelta(days=30), d + timedelta(days=39), -1.0, ticker="BBB"),
        _trade(d + timedelta(days=60), d + timedelta(days=69), 3.0, ticker="AAA"),
    ]
    spy = (np.array([]), np.array([]), np.array([], dtype="datetime64[ns]"))
    base = _random_baseline_trades(
        data, ref, date(2023, 1, 1), date(2024, 12, 31),
        spy[0], spy[1], spy[2], seed=42)
    assert len(base) == len(ref)
    ref_durations = sorted((t.exit_date - t.entry_date).days for t in ref)
    base_durations = sorted((t.exit_date - t.entry_date).days for t in base)
    assert base_durations == ref_durations
    # Baseline entries are T+1 opens with slippage, never the raw close.
    for t in base:
        assert t.entry_price > 0 and t.exit_price > 0
        assert t.risk_pct is None
        assert t.regime_calendar in ("bull_2023_2024", "recent_2025")


def test_random_baseline_is_deterministic_per_seed():
    data = {"AAA": _flat_history("AAA")}
    d = date(2024, 1, 2)
    ref = [_trade(d, d + timedelta(days=9), 2.0, ticker="AAA")]
    spy = (np.array([]), np.array([]), np.array([], dtype="datetime64[ns]"))
    args = (data, ref, date(2023, 1, 1), date(2024, 12, 31), spy[0], spy[1], spy[2])
    first = _random_baseline_trades(*args, seed=123)
    second = _random_baseline_trades(*args, seed=123)
    assert [(t.ticker, t.entry_date, t.pnl_pct) for t in first] == [
        (t.ticker, t.entry_date, t.pnl_pct) for t in second
    ]
    other = _random_baseline_trades(*args, seed=124)
    assert [(t.entry_date, t.pnl_pct) for t in other] != [
        (t.entry_date, t.pnl_pct) for t in first
    ]


def test_baseline_summary_runs_simulator():
    data = {"AAA": _flat_history("AAA"), "BBB": _flat_history("BBB")}
    d = date(2024, 1, 2)
    ref = [
        _trade(d, d + timedelta(days=9), 2.0, ticker="AAA"),
        _trade(d + timedelta(days=30), d + timedelta(days=39), -1.0, ticker="BBB"),
    ]
    spy = (np.array([]), np.array([]), np.array([], dtype="datetime64[ns]"))
    summary = _baseline_summary(
        data, ref, date(2023, 1, 1), date(2024, 12, 31),
        spy[0], spy[1], spy[2], n_seeds=2, seed=42)
    assert summary["n_seeds"] == 2
    assert summary["per_trade"]["trade_count"] == len(ref)
    assert summary["simulator"]["trades_taken"] > 0
    assert "expectancy_pct" in summary["simulator"]
    assert "max_drawdown_pct" in summary["simulator"]
