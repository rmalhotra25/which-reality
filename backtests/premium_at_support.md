# Backtest: Premium at Support (Wheel)
Generated: 2026-10-23
**Data source**: SYNTHETIC (mechanics verification only, not market evidence)

> **DATA NOTE: SYNTHETIC** -- this report was generated on procedurally generated random-walk price data because yfinance had no network access in the test environment.  All structural requirements (regime splits, walk-forward, robustness, etc.) are present and mechanically correct.  Rerun with live data on a networked deployment for real edge measurements.

## Cost Assumptions
- Slippage: 0.05% per side (applied to T+1 open)
- Commission: $0.65 per options contract; $0 for stock
- Modeled spread haircut (Setup 2 only): 5% of premium

## Survivorship Caveat
Tested on currently listed names only; survivorship bias may flatter long-side results.

## Rule Definition
```
Universe: S&P 500 + Dividend Achievers
Signal (close of day T):
  price within 2% of 50-day MA (above or below)
  200-day MA rising
  HV percentile in top third of trailing year
  [IV percentile substitution: HV used as IV proxy; stated in every reference]
Entry: T+1 open (stock signal); modeled put entered same day
Modeled trade: sell 30-delta put, 37 DTE, Black-Scholes with HV;
  5% spread haircut; close at 50% profit or 21 DTE;
  assignment modeled if ITM at expiry
Stock exit: stop on close below 200 MA; time stop 30 days
Options P&L: MODELED everywhere it appears
```

## Universe and Periods
- Universe: S&P 500 + Dividend Achievers (20 tickers)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-23

## Options Model Note
All options P&L figures are **MODELED** using Black-Scholes with historical volatility as the IV proxy.  Real IV was not available for historical dates.  The HV-as-IV substitution is stated here and in every table that shows options P&L.  Stock-signal quality (did support hold) is reported separately.

## Stock Signal Quality Note
Stock signal quality: support held (trade profitable) on 26.1% of trades (n=476).  This is the stock-side edge only, independent of the options model.

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 238  |  Win rate: 25.6% (info only)
    Expectancy/trade: 0.394%  |  Profit factor: 1.31
    Avg win: 6.44%  |  Avg loss: 1.69%
    Max drawdown: 31.26%
  Out-of-sample (2023-present)
    Trades: 238  |  Win rate: 26.5% (info only)
    Expectancy/trade: 0.431%  |  Profit factor: 1.33
    Avg win: 6.64%  |  Avg loss: 1.80%
    Max drawdown: 46.21%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 75  |  Win rate: 28.0% (info only)
    Expectancy/trade: 0.779%  |  Profit factor: 1.67
    Avg win: 6.93%  |  Avg loss: 1.61%
    Max drawdown: 17.63%
  Bull 2023-2024
    Trades: 138  |  Win rate: 25.4% (info only)
    Expectancy/trade: 0.315%  |  Profit factor: 1.22
    Avg win: 6.89%  |  Avg loss: 1.92%
    Max drawdown: 33.13%
  Recent 2025
    Trades: 263  |  Win rate: 25.9% (info only)
    Expectancy/trade: 0.360%  |  Profit factor: 1.29
    Avg win: 6.24%  |  Avg loss: 1.69%
    Max drawdown: 39.55%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 258  |  Win rate: 25.2% (info only)
    Expectancy/trade: 0.048%  |  Profit factor: 1.03
    Avg win: 5.76%  |  Avg loss: 1.88%
    Max drawdown: 41.32%
  SPY below 200 MA
    Trades: 218  |  Win rate: 27.1% (info only)
    Expectancy/trade: 0.845%  |  Profit factor: 1.73
    Avg win: 7.40%  |  Avg loss: 1.59%
    Max drawdown: 34.31%

## Robustness Tests (+/- 20% on key parameters)
  support_pct -20% (=0.016): n=210  exp=0.411%  PF=1.28
  support_pct +20% (=0.024): n=270  exp=0.497%  PF=1.41
  hv_pct_thresh -20% (=0.5333): n=331  exp=0.514%  PF=1.42
  hv_pct_thresh +20% (=0.8): n=152  exp=0.516%  PF=1.40

Edge survives across +/-20% parameter variations.

## Verdict
**SHADOW ONLY** -- synthetic data: mechanics verification only, not market evidence
