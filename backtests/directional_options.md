# Backtest: Directional Options (Phase 3A, long calls and puts)

**Data source**: REAL live grading of journaled picks, not a backtest simulation: 64 picks made, 11 settled, 0% win rate, -$10,595 option P&L as of 2026-10-26. No walk-forward backtest with a PASSES verdict exists for this setup.

**SHADOW ONLY**

## Why SHADOW

Live grading is the evidence that matters here, and it fails: 11 settled
picks, zero winners, -$10,595. That is a small settled sample, so it is
not proof the setup can never work, but it is proof it has not earned
LIVE status. A setup may go LIVE only when a backtest stamped with real
data carries a verdict of PASSES, and this setup has no such backtest.

## Rule Definition

Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py).
Signal: DirectionalEngine builds one candidate per ticker from the
listed 21 DTE chain, ranked by expiry-consistent EV per $ risked
(see services/directional_ranker.py). P(profit) is P(stock finishes
past breakeven) from the contract IV. Entry: listed contract premium
(ask, else last trade, else fair value). Exit: premium stop at -50%
of entry premium, target, or expiry.

## What would promote it

A walk-forward backtest on real historical option prices (not modelled
premiums) with out-of-sample expectancy above $0 and profit factor
above 1.2, plus live grading that no longer shows a 0% win rate on a
settled sample of at least 30. Until then the setup stays SHADOW:
candidates are shown for observation only, journaled for grading, and
never sent as LIVE Challenge alerts or Telegram alerts.
