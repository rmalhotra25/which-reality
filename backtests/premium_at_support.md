# Backtest: Premium at Support (Wheel)
Generated: 2026-10-24
**Data source**: REAL (fetched 2026-10-24)

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
- Universe: S&P 500 + Dividend Achievers (543 tickers)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-24

## Options Model Note
All options P&L figures are **MODELED** using Black-Scholes with historical volatility as the IV proxy.  Real IV was not available for historical dates.  The HV-as-IV substitution is stated here and in every table that shows options P&L.  Stock-signal quality (did support hold) is reported separately.

## Stock Signal Quality Note
Stock signal quality: support held (trade profitable) on 30.6% of trades (n=8036).  This is the stock-side edge only, independent of the options model.

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 3701  |  Win rate: 28.7% (info only)
    Expectancy/trade: 0.695%  |  Profit factor: 1.48
    Avg win: 7.51%  |  Avg loss: 2.04%
    Max drawdown: 62.69%
  Out-of-sample (2023-present)
    Trades: 4335  |  Win rate: 32.2% (info only)
    Expectancy/trade: 1.270%  |  Profit factor: 2.02
    Avg win: 7.79%  |  Avg loss: 1.83%
    Max drawdown: 63.89%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 1716  |  Win rate: 25.1% (info only)
    Expectancy/trade: 0.443%  |  Profit factor: 1.37
    Avg win: 6.58%  |  Avg loss: 1.61%
    Max drawdown: 79.23%
  Bull 2023-2024
    Trades: 1715  |  Win rate: 37.1% (info only)
    Expectancy/trade: 1.639%  |  Profit factor: 2.37
    Avg win: 7.64%  |  Avg loss: 1.90%
    Max drawdown: 42.96%
  Recent 2025
    Trades: 4605  |  Win rate: 30.2% (info only)
    Expectancy/trade: 0.978%  |  Profit factor: 1.68
    Avg win: 8.01%  |  Avg loss: 2.07%
    Max drawdown: 86.00%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 5518  |  Win rate: 31.9% (info only)
    Expectancy/trade: 0.966%  |  Profit factor: 1.67
    Avg win: 7.52%  |  Avg loss: 2.11%
    Max drawdown: 57.98%
  SPY below 200 MA
    Trades: 2518  |  Win rate: 27.6% (info only)
    Expectancy/trade: 1.091%  |  Profit factor: 1.97
    Avg win: 8.03%  |  Avg loss: 1.56%
    Max drawdown: 55.81%

## Robustness Tests (+/- 20% on key parameters)
  support_pct -20% (=0.016): n=236  exp=1.385%  PF=1.94
  support_pct +20% (=0.024): n=276  exp=1.203%  PF=1.89
  hv_pct_thresh -20% (=0.5333): n=356  exp=1.551%  PF=2.19
  hv_pct_thresh +20% (=0.8): n=158  exp=1.171%  PF=1.74

Edge survives across +/-20% parameter variations.

## Verdict
**SHADOW ONLY**
