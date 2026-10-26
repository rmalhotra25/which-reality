# Backtest: Quality Pullback
Generated: 2026-10-26
**Data source**: REAL (fetched 2026-10-26)

## Cost Assumptions
- Slippage: 0.05% per side (applied to T+1 open)
- Commission: $0.65 per options contract; $0 for stock
- Modeled spread haircut (Setup 2 only): 5% of premium

## Survivorship Caveat
Tested on currently listed names only; survivorship bias may flatter long-side results.

## Rule Definition
```
Universe: S&P 500 + Dividend Achievers with >=5y history
Signal (close of day T):
  price within 2% ABOVE 50-day or 200-day MA
  200-day MA rising (today > value 20 days ago)
  RSI(14) < 55 now and was > 60 within prior 20 sessions
  volume < 20-day average volume
  [earnings filter: skipped -- unavailable at backtest time]
Entry: T+1 open + 0.05% slippage
Exit: stop on close below 200 MA; target when RSI(14) > 68; time stop 30 days
```

## Universe and Periods
- Universe: S&P 500 + Dividend Achievers (543 tickers combined)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-26

## Walk-Forward Results
Per-trade stats below compound each trade at 100% of the account in date order. That max drawdown is not a portfolio drawdown; the portfolio drawdown is in the Portfolio Simulator section.
  In-sample (2019-2022)
    Trades: 5096  |  Win rate: 48.2% (info only)
    Expectancy/trade: 0.794%  |  Profit factor: 1.57
    Avg win: 4.54%  |  Avg loss: 2.68%
    Max drawdown: 99.93%
  Out-of-sample (2023-present)
    Trades: 6823  |  Win rate: 46.6% (info only)
    Expectancy/trade: 0.586%  |  Profit factor: 1.43
    Avg win: 4.18%  |  Avg loss: 2.56%
    Max drawdown: 99.86%

## Regime Splits
### Calendar regimes
  Pre-2022
    Trades: 3673  |  Win rate: 51.9% (info only)
    Expectancy/trade: 1.044%  |  Profit factor: 1.75
    Avg win: 4.68%  |  Avg loss: 2.89%
    Max drawdown: 99.93%
  Bear 2022
    Trades: 1423  |  Win rate: 38.4% (info only)
    Expectancy/trade: 0.148%  |  Profit factor: 1.11
    Avg win: 4.02%  |  Avg loss: 2.27%
    Max drawdown: 97.78%
  Bull 2023-2024
    Trades: 3654  |  Win rate: 47.9% (info only)
    Expectancy/trade: 0.616%  |  Profit factor: 1.46
    Avg win: 4.10%  |  Avg loss: 2.59%
    Max drawdown: 98.82%
  Recent 2025
    Trades: 3169  |  Win rate: 45.1% (info only)
    Expectancy/trade: 0.552%  |  Profit factor: 1.40
    Avg win: 4.29%  |  Avg loss: 2.52%
    Max drawdown: 99.62%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 10155  |  Win rate: 48.4% (info only)
    Expectancy/trade: 0.696%  |  Profit factor: 1.49
    Avg win: 4.36%  |  Avg loss: 2.74%
    Max drawdown: 99.99%
  SPY below 200 MA
    Trades: 1764  |  Win rate: 40.9% (info only)
    Expectancy/trade: 0.552%  |  Profit factor: 1.47
    Avg win: 4.19%  |  Avg loss: 1.97%
    Max drawdown: 90.31%

## Robustness Tests (+/- 20% on key parameters)
  pullback_pct -20% (=0.016): n=402  exp=0.676%  PF=1.57
  pullback_pct +20% (=0.024): n=458  exp=0.862%  PF=1.75
  rsi_entry -20% (=44): n=276  exp=0.970%  PF=1.90
  rsi_entry +20% (=66): n=547  exp=0.601%  PF=1.53
  rsi_reset -20% (=48): n=430  exp=0.771%  PF=1.66
  rsi_reset +20% (=72): n=430  exp=0.771%  PF=1.66

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**

## Portfolio Simulator and Random-Entry Baseline (2026-10-26)
Simulator settings: 1% of current equity risked per trade, sized by distance to the stop where known, otherwise by the 10% per-position notional cap; max 10 concurrent positions; total open risk capped at 10% of equity; risk halves at a 10% equity drawdown and new entries pause at a 15% drawdown, resuming below 10%. Starting equity $100,000. Open positions are marked at cost, so the equity curve moves on realized exits only and intra-trade drawdown is not captured.

### Portfolio simulator, out-of-sample trades
  Setup through simulator
    Trades taken: 1993  |  Skipped: 4830 (max positions 4810, heat 0, paused 0, cash 20)
    Expectancy/trade: 0.331%  |  Profit factor: 1.41
    Start equity: $100,000.00  |  Final equity: $173,983.87  |  Total return: 73.98%
    CAGR: 15.68%  |  Portfolio max drawdown: 9.65% ($13,500.99)
    Calmar ratio: 1.63  |  Recovery factor: 5.48
    Avg trade duration: 6.1 days  |  Max concurrent positions: 10

### Random-entry baseline, out-of-sample
Random entries, same universe and holding periods as the setup, same T+1 open entry and costs, averaged across 5 seeds (seed base 42), run through the same portfolio simulator.
  Baseline per-trade (mean across seeds)
    Trades: 6823  |  Win rate: 51.9% (info only)
    Expectancy/trade: 0.511%  |  Profit factor: 1.28
    Avg win: 4.53%  |  Avg loss: 3.83%
    Max drawdown: 99.99%
  Baseline through simulator
    Trades taken: 509.2  |  Skipped: 6313.8 (max positions 564.6, heat 0.0, paused 5101.2, cash 648.0)
    Expectancy/trade: -0.283%  |  Profit factor: 0.80
    Start equity: $100,000.00  |  Final equity: $92,349.95  |  Total return: -7.65%
    CAGR: -2.13%  |  Portfolio max drawdown: 16.64% ($18,203.74)
    Calmar ratio: -0.12  |  Recovery factor: -0.44
    Avg trade duration: 6.8 days  |  Max concurrent positions: 10.0

Setup beats its random-entry baseline: yes (setup simulator expectancy 0.331% vs baseline -0.283%; setup profit factor 1.41 vs baseline 0.804). The registry verdict above is unchanged by this comparison; the baseline is reported so the edge can be judged against doing nothing.

### Prior run, preserved
Per-trade numbers from the 2026-10-24 report run, preserved when this report regenerated. The max drawdown below is the old ticker-ordered sequential figure, known broken, and is kept for history only; the portfolio drawdown in the simulator section above replaces it.
  Out-of-sample (2023-present)
    Trades: 6828  |  Win rate: 46.7% (info only)
    Expectancy/trade: 0.589%  |  Profit factor: 1.43
    Avg win: 4.18%  |  Avg loss: 2.55%
    Max drawdown: 88.06%
