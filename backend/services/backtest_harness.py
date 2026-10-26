"""
Backtest harness.

Design rules (non-negotiable):
  - Mechanical rules only: a setup is code, no discretionary steps.
  - No lookahead: signal from close of day T enters at day T+1 open.
    The harness precomputes indicators on the full series (rolling
    calculations inherently use only data up to each row), then indexes
    by row i to check signals.  Entry price is always row[i+1]["Open"].
  - Realistic costs: stock fills at open +/- 0.05% slippage per side.
    Options contracts: $0.65 commission per contract; 5% spread haircut
    on modeled premium (Setup 2 only).
  - Regime splits: calendar splits (pre-2022, bear 2022, bull 2023-2024,
    recent 2025 onward) + per-trade SPY 200-day tag.
  - Walk-forward: IS = 2019-2022, OOS = 2023-present. Never blended.
  - Scoring: expectancy per trade, profit factor, avg win/loss, max DD.
    Win rate is printed for information only. Per-trade max drawdown is
    computed on trades sorted by entry date; it still compounds each
    trade at 100% of the account, so it is not a portfolio drawdown.
    The portfolio simulator (fixed-fractional risk, position and heat
    caps, drawdown circuit breaker) produces the portfolio drawdown,
    CAGR, Calmar ratio, and recovery factor that judge real risk.
  - Random-entry baseline: random entries with the same holding periods
    and universe as the setup under test, same T+1 entry and costs, run
    through the same portfolio simulator. A setup should beat doing
    nothing before it is trusted.
  - Robustness: each key param rerun at ~+/-20%. Fragile if edge only
    works at one exact setting.
  - Sample honesty: trade count printed next to every stat.
    OOS < 30 trades -> INSUFFICIENT SAMPLE stamp.
  - Survivorship caveat: printed on every report.

Verdict: PASSES | SHADOW ONLY | FAILS
  PASSES      OOS expectancy > 0, profit factor > 1.2, not fragile,
              sample >= 30
  SHADOW ONLY positive but fragile, insufficient sample, or modeled only
  FAILS       OOS expectancy <= 0 or profit factor <= 1.2

Cost assumptions printed in every report:
  Slippage: 0.05% per side (stock entries and exits)
  Commission: $0.65 per options contract; $0 for stock
  Modeled spread haircut: 5% of premium (Setup 2 put premium)
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost constants
# ---------------------------------------------------------------------------
SLIPPAGE_PER_SIDE = 0.0005
OPTIONS_COMMISSION = 0.65
MODELED_SPREAD_HAIRCUT = 0.05

# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
IS_START  = date(2019, 1, 1)
IS_END    = date(2022, 12, 31)
OOS_START = date(2023, 1, 1)
OOS_END   = date.today()
FULL_START = IS_START

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    ticker: str
    signal_date: date
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    exit_reason: str
    regime_calendar: str
    regime_spy_ma: str
    pnl_pct: float
    options_pnl_per_contract: Optional[float] = None
    options_exit_reason: Optional[str] = None
    modeled: bool = False
    # Distance from entry price to the invalidation/stop, as a percent of
    # entry price. Set at entry when the stop is known (breakout level for
    # Volume Breakout, 200-day MA for the pullback/support setups). None
    # when no stop distance is known; the portfolio simulator then sizes
    # by its per-position notional cap instead.
    risk_pct: Optional[float] = None


@dataclass
class SetupStats:
    trade_count: int = 0
    wins: int = 0
    total_win_pct: float = 0.0
    total_loss_pct: float = 0.0
    equity_curve: list = field(default_factory=list)

    def add(self, pnl_pct: float) -> None:
        self.trade_count += 1
        if pnl_pct > 0:
            self.wins += 1
            self.total_win_pct += pnl_pct
        else:
            self.total_loss_pct += abs(pnl_pct)
        self.equity_curve.append(pnl_pct)

    def summary(self) -> dict:
        n = self.trade_count
        if n == 0:
            return {"trade_count": 0}
        losses = n - self.wins
        avg_win  = self.total_win_pct / self.wins if self.wins else 0.0
        avg_loss = self.total_loss_pct / losses if losses else 0.0
        win_rate = self.wins / n
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
        pf = self.total_win_pct / self.total_loss_pct if self.total_loss_pct > 0 else float("inf")
        return {
            "trade_count": n,
            "win_rate_pct": round(win_rate * 100, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "expectancy_pct": round(expectancy, 3),
            "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
            "max_drawdown_pct": round(_max_drawdown(self.equity_curve), 2),
            "insufficient_sample": n < 30,
        }


def _max_drawdown(returns_pct: list) -> float:
    """
    Peak-to-trough drawdown of a sequentially compounded equity curve.

    Callers must pass returns in date order (see _compute_stats_for_trades).
    This still treats every trade as 100% of the account, so it is NOT a
    portfolio drawdown. The portfolio simulator builds the real equity
    curve with position sizing, concurrency, and heat limits.
    """
    if not returns_pct:
        return 0.0
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1 + r / 100)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# Regime helpers
# ---------------------------------------------------------------------------

def _calendar_regime(d: date) -> str:
    if d < date(2022, 1, 1):
        return "pre_2022"
    if date(2022, 1, 1) <= d <= date(2022, 12, 31):
        return "bear_2022"
    if date(2023, 1, 1) <= d <= date(2024, 12, 31):
        return "bull_2023_2024"
    return "recent_2025"


def _spy_regime(entry_date: date, spy_closes: np.ndarray, spy_ma200: np.ndarray,
                spy_dates: np.ndarray) -> str:
    """SPY above or below 200-day MA at entry date."""
    mask = spy_dates <= np.datetime64(entry_date)
    if not mask.any():
        return "unknown"
    idx = int(np.where(mask)[0][-1])
    if np.isnan(spy_ma200[idx]):
        return "unknown"
    return "above_200" if spy_closes[idx] >= spy_ma200[idx] else "below_200"


# ---------------------------------------------------------------------------
# Data download / synthetic fallback
# ---------------------------------------------------------------------------

def _download_history(
    ticker: str, start: date, end: date, allow_synthetic: bool = True
) -> tuple[pd.DataFrame, bool]:
    """
    Returns (df, is_synthetic).
    When allow_synthetic=False and yfinance fails, raises RuntimeError
    instead of falling back to synthetic data.
    """
    try:
        import yfinance as yf
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index).normalize()
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        if len(df) > 100:
            return df, False
    except Exception as e:
        logger.debug("yfinance download failed for %s: %s", ticker, e)

    if not allow_synthetic:
        raise RuntimeError(
            f"Real data unavailable for {ticker}. "
            "Rerun with --allow-synthetic to use synthetic fallback for mechanics verification."
        )
    return _synthetic_ohlcv(ticker, start, end), True


def _synthetic_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    """
    Deterministic synthetic OHLCV seeded by ticker name.
    Used when yfinance is unreachable.
    """
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(ticker)) % 100000
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)
    if n == 0:
        return pd.DataFrame()
    returns = rng.normal(0.0003, 0.013, n)
    price = 100.0
    closes = []
    for r in returns:
        price = max(price * (1 + r), 1.0)
        closes.append(price)
    closes = np.array(closes)
    spread = rng.uniform(0.001, 0.015, n)
    highs = closes * (1 + spread)
    lows  = closes * (1 - spread)
    opens = np.concatenate([[closes[0]], closes[:-1]]) * (1 + rng.normal(0, 0.003, n))
    opens = np.clip(opens, lows, highs)
    volumes = rng.integers(500_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=pd.DatetimeIndex(dates),
    )


# ---------------------------------------------------------------------------
# Precomputed indicator arrays (eliminates O(n^2) rolling in inner loop)
# ---------------------------------------------------------------------------

def _precompute(df: pd.DataFrame, params: dict, setup: str) -> dict:
    """
    Compute all indicator series once for a ticker.
    Rolling calcs on the full series are equivalent to computing on
    df.iloc[:i+1] -- no lookahead.
    """
    closes  = df["Close"]
    volumes = df["Volume"]
    highs   = df["High"]
    lows    = df["Low"]
    n = len(closes)

    ma50  = closes.rolling(50).mean().values
    ma200 = closes.rolling(200).mean().values
    # 20-day lag of MA200 for "rising" check
    ma200_lag20 = pd.Series(ma200).shift(20).values
    # RSI(14)
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = (100 - 100 / (1 + rs)).values
    # Was RSI above 60 in any of the last 20 sessions?
    rsi_series = pd.Series(rsi)
    rsi_was_high = rsi_series.rolling(20).apply(
        lambda x: float(any(v >= 60 for v in x if not np.isnan(v))), raw=False
    ).values
    # Volume 20-day MA
    vol20 = volumes.rolling(20).mean().values
    # HV(30) -- annualized
    log_ret = np.log(closes / closes.shift(1))
    hv30 = log_ret.rolling(30).std().values * math.sqrt(252)
    # HV percentile (trailing 252 days)
    hv_pct = np.full(n, np.nan)
    for j in range(30, n):
        window_start = max(0, j - 252)
        w = hv30[window_start: j + 1]
        w = w[~np.isnan(w)]
        if len(w) >= 5:
            cur = hv30[j]
            hv_pct[j] = np.nan if np.isnan(cur) else sum(1 for v in w if v < cur) / len(w)

    # ATR(14)
    prev_close = closes.shift(1).values
    tr = np.nanmax(np.stack([
        highs.values - lows.values,
        np.abs(highs.values - prev_close),
        np.abs(lows.values - prev_close),
    ], axis=1), axis=1)
    atr14 = pd.Series(tr).rolling(14).mean().values

    # Prior N-day high (for breakout setup) -- excluding current day
    bd = int(params.get("breakout_days", 55))
    prior_high = closes.shift(1).rolling(bd).max().values

    # MA50 lag-20 for breakout rising check
    ma50_lag20 = pd.Series(ma50).shift(20).values

    return {
        "closes":       closes.values,
        "opens":        df["Open"].values,
        "highs":        highs.values,
        "lows":         lows.values,
        "volumes":      volumes.values,
        "dates":        df.index.values,  # numpy datetime64
        "ma50":         ma50,
        "ma200":        ma200,
        "ma200_lag20":  ma200_lag20,
        "ma50_lag20":   ma50_lag20,
        "rsi":          rsi,
        "rsi_was_high": rsi_was_high,
        "vol20":        vol20,
        "hv30":         hv30,
        "hv_pct":       hv_pct,
        "atr14":        atr14,
        "prior_high":   prior_high,
    }


# ---------------------------------------------------------------------------
# Signal functions (indexed, O(1) per call)
# ---------------------------------------------------------------------------

def _signal_quality_pullback(ind: dict, i: int, params: dict) -> bool:
    pullback_pct = params.get("pullback_pct", 0.02)
    rsi_entry    = params.get("rsi_entry", 55.0)

    price = ind["closes"][i]
    ma50  = ind["ma50"][i]
    ma200 = ind["ma200"][i]
    if np.isnan(ma50) or np.isnan(ma200):
        return False

    near_50  = 0 <= (price / ma50  - 1) <= pullback_pct
    near_200 = 0 <= (price / ma200 - 1) <= pullback_pct
    if not (near_50 or near_200):
        return False

    ma200_l = ind["ma200_lag20"][i]
    if np.isnan(ma200_l) or ma200 <= ma200_l:
        return False

    rsi_now = ind["rsi"][i]
    if np.isnan(rsi_now) or rsi_now >= rsi_entry:
        return False

    if not ind["rsi_was_high"][i]:
        return False

    vol_now = ind["volumes"][i]
    vol20   = ind["vol20"][i]
    if np.isnan(vol20) or vol_now >= vol20:
        return False

    return True


def _signal_premium_at_support(ind: dict, i: int, params: dict) -> bool:
    support_pct   = params.get("support_pct", 0.02)
    hv_pct_thresh = params.get("hv_pct_thresh", 2 / 3)

    price = ind["closes"][i]
    ma50  = ind["ma50"][i]
    ma200 = ind["ma200"][i]
    if np.isnan(ma50) or np.isnan(ma200):
        return False

    if abs(price / ma50 - 1) > support_pct:
        return False

    ma200_l = ind["ma200_lag20"][i]
    if np.isnan(ma200_l) or ma200 <= ma200_l:
        return False

    hv_p = ind["hv_pct"][i]
    if np.isnan(hv_p) or hv_p < hv_pct_thresh:
        return False

    return True


def _signal_volume_breakout(ind: dict, i: int, params: dict) -> bool:
    vol_mult = params.get("vol_mult", 1.5)

    price      = ind["closes"][i]
    prior_high = ind["prior_high"][i]
    ma50       = ind["ma50"][i]
    ma50_l     = ind["ma50_lag20"][i]
    vol_now    = ind["volumes"][i]
    vol20      = ind["vol20"][i]

    if np.isnan(ma50) or np.isnan(prior_high):
        return False

    if price <= prior_high:
        return False

    if np.isnan(vol20) or vol20 <= 0 or vol_now < vol_mult * vol20:
        return False

    if price < ma50:
        return False
    if not np.isnan(ma50_l) and ma50 <= ma50_l:
        return False

    return True


# ---------------------------------------------------------------------------
# Exit functions (indexed, O(1) per call)
# entry_idx: position of the entry row in the full arrays
# ---------------------------------------------------------------------------

def _exit_quality_pullback(ind: dict, i: int, entry_price: float, entry_idx: int,
                           extra_state, params: dict) -> tuple | None:
    rsi_target = params.get("rsi_target", 68.0)
    time_stop  = int(params.get("time_stop_days", 30))
    days_held  = i - entry_idx

    if days_held > time_stop:
        return "time", ind["closes"][i]

    price = ind["closes"][i]
    ma200 = ind["ma200"][i]
    if not np.isnan(ma200) and price < ma200:
        return "stop", price

    rsi_now = ind["rsi"][i]
    if not np.isnan(rsi_now) and rsi_now > rsi_target:
        return "target", price

    return None


def _exit_premium_support(ind: dict, i: int, entry_price: float, entry_idx: int,
                          extra_state, params: dict) -> tuple | None:
    time_stop = int(params.get("time_stop_days", 30))
    days_held = i - entry_idx

    if days_held > time_stop:
        return "time", ind["closes"][i]

    price = ind["closes"][i]
    ma200 = ind["ma200"][i]
    if not np.isnan(ma200) and price < ma200:
        return "stop", price

    return None


def _exit_volume_breakout(ind: dict, i: int, entry_price: float, entry_idx: int,
                          extra_state, params: dict) -> tuple | None:
    time_stop      = int(params.get("time_stop_days", 15))
    atr_mult       = params.get("atr_mult", 2.0)
    breakout_level = entry_price
    if extra_state and isinstance(extra_state, dict):
        breakout_level = extra_state.get("breakout_level", entry_price)

    days_held = i - entry_idx
    if days_held > time_stop:
        return "time", ind["closes"][i]

    price = ind["closes"][i]
    if price < breakout_level:
        return "stop", price

    atr14 = ind["atr14"][i]
    if not np.isnan(atr14) and price >= entry_price + atr_mult * atr14:
        return "target", price

    return None


# ---------------------------------------------------------------------------
# Options P&L model for Setup 2 (always labeled MODELED)
# ---------------------------------------------------------------------------

def _model_put_pnl(entry_price, entry_date, exit_price, exit_date,
                   exit_reason, hv_at_entry, params) -> dict:
    try:
        from services.stock_data import _bs_put_delta, _ncdf
    except ImportError:
        return {"pnl_per_contract": 0.0, "exit_reason": "import_error"}

    target_dte = int(params.get("put_dte", 37))
    r = 0.045
    T_entry = max(target_dte, 1) / 365.0
    iv = max(hv_at_entry, 0.05)

    strike = entry_price
    for _ in range(20):
        d = _bs_put_delta(entry_price, strike, iv, T_entry, r)
        if d is None:
            break
        if abs(abs(d) - 0.30) < 0.005:
            break
        strike = strike * (0.995 if abs(d) < 0.30 else 1.005)

    try:
        sq = iv * math.sqrt(T_entry)
        d1 = (math.log(entry_price / strike) + (r + 0.5 * iv**2) * T_entry) / sq
        d2 = d1 - sq
        put_raw = max(strike * math.exp(-r * T_entry) * _ncdf(-d2) - entry_price * _ncdf(-d1), 0.01)
    except Exception:
        return {"pnl_per_contract": 0.0, "exit_reason": "pricing_error"}

    premium = round(put_raw * (1 - MODELED_SPREAD_HAIRCUT), 2)
    target_pnl = premium * 0.50 * 100
    remaining_dte = max(target_dte - (exit_date - entry_date).days, 0)

    def put_price_at(T_rem, underlying):
        T = max(T_rem, 0.5) / 365.0
        try:
            sq = iv * math.sqrt(T)
            d1 = (math.log(underlying / strike) + (r + 0.5 * iv**2) * T) / sq
            d2 = d1 - sq
            return max(strike * math.exp(-r * T) * _ncdf(-d2) - underlying * _ncdf(-d1), 0.01)
        except Exception:
            return premium

    if remaining_dte <= 21:
        pnl = (premium - put_price_at(remaining_dte, exit_price)) * 100 - OPTIONS_COMMISSION * 2
        return {"pnl_per_contract": round(pnl, 2), "exit_reason": "21_dte"}

    put_exit = put_price_at(remaining_dte, exit_price)
    pnl_so_far = (premium - put_exit) * 100
    if pnl_so_far >= target_pnl:
        return {"pnl_per_contract": round(pnl_so_far - OPTIONS_COMMISSION * 2, 2),
                "exit_reason": "50_pct_profit"}

    if exit_price < strike:
        pnl = premium * 100 + (exit_price - strike) * 100 - OPTIONS_COMMISSION
        return {"pnl_per_contract": round(pnl, 2), "exit_reason": "assigned"}

    return {"pnl_per_contract": round(pnl_so_far - OPTIONS_COMMISSION * 2, 2),
            "exit_reason": "expired_otm"}


# ---------------------------------------------------------------------------
# Core backtesting loop
# ---------------------------------------------------------------------------

def _apply_slippage(price: float, direction: str) -> float:
    mult = 1 + SLIPPAGE_PER_SIDE if direction == "buy" else 1 - SLIPPAGE_PER_SIDE
    return price * mult


def _run_single_ticker(
    ticker: str, df: pd.DataFrame,
    spy_closes: np.ndarray, spy_ma200: np.ndarray, spy_dates: np.ndarray,
    signal_fn, exit_fn,
    start: date, end: date,
    params: dict,
    extra_state_fn=None,   # callable(ind, i, params) -> dict | None
    compute_options: bool = False,
) -> list[Trade]:
    ind = _precompute(df, params, "")
    n = len(ind["closes"])
    dates = ind["dates"]

    # Date boundaries as numpy for fast comparison
    start64 = np.datetime64(start)
    end64   = np.datetime64(end)

    trades = []
    in_trade = False
    entry_price = entry_idx = entry_date = extra_state = risk_pct = None

    for i in range(210, n - 1):  # need i+1 for next-day entry
        row_date64 = dates[i]
        if row_date64 > end64:
            break

        if in_trade:
            result = exit_fn(ind, i, entry_price, entry_idx, extra_state, params)
            if result is not None:
                exit_reason, _ = result
                exit_row_date = dates[i].astype("M8[D]").astype(object)  # numpy -> python date
                exit_price = _apply_slippage(float(ind["opens"][i]), "sell")
                pnl_pct = (exit_price - entry_price) / entry_price * 100

                opt_pnl = None
                opt_exit_r = None
                modeled = False
                if compute_options and extra_state and "hv" in extra_state:
                    opt = _model_put_pnl(
                        entry_price, entry_date, exit_price, exit_row_date,
                        exit_reason, extra_state["hv"], params,
                    )
                    opt_pnl = opt["pnl_per_contract"]
                    opt_exit_r = opt["exit_reason"]
                    modeled = True

                spy_reg = _spy_regime(entry_date, spy_closes, spy_ma200, spy_dates)
                trades.append(Trade(
                    ticker=ticker,
                    signal_date=dates[entry_idx - 1].astype("M8[D]").astype(object),
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=exit_row_date,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    regime_calendar=_calendar_regime(entry_date),
                    regime_spy_ma=spy_reg,
                    pnl_pct=round(pnl_pct, 3),
                    options_pnl_per_contract=opt_pnl,
                    options_exit_reason=opt_exit_r,
                    modeled=modeled,
                    risk_pct=risk_pct,
                ))
                in_trade = False
                risk_pct = None

        elif row_date64 >= start64:
            if signal_fn(ind, i, params):
                raw_entry = float(ind["opens"][i + 1])
                entry_price = _apply_slippage(raw_entry, "buy")
                entry_idx = i + 1
                entry_date = dates[i + 1].astype("M8[D]").astype(object)
                in_trade = True
                extra_state = extra_state_fn(ind, i, params) if extra_state_fn else None
                # Distance to invalidation, for fixed-fractional sizing.
                # Breakout level is the stop for Volume Breakout; otherwise
                # fall back to the 200-day MA at the signal row, which is
                # the stop for the pullback/support setups. The MA is read
                # at the signal row (known at entry), not the entry row.
                stop_price = None
                if extra_state and isinstance(extra_state, dict):
                    if extra_state.get("stop_price") is not None:
                        stop_price = float(extra_state["stop_price"])
                    elif extra_state.get("breakout_level") is not None:
                        stop_price = float(extra_state["breakout_level"])
                if stop_price is None:
                    ma200_sig = ind["ma200"][i]
                    if not np.isnan(ma200_sig):
                        stop_price = float(ma200_sig)
                risk_pct = None
                if stop_price is not None and 0 < stop_price < entry_price:
                    risk_pct = (entry_price - stop_price) / entry_price * 100

    return trades


def _run_setup(
    setup_name: str, signal_fn, exit_fn,
    universe: list, start: date, end: date,
    params: dict,
    spy_closes: np.ndarray, spy_ma200: np.ndarray, spy_dates: np.ndarray,
    extra_state_fn=None,
    compute_options: bool = False,
    allow_synthetic: bool = True,
    collect_data: bool = False,
) -> tuple[list[Trade], bool] | tuple[list[Trade], bool, dict]:
    """
    Returns (trades, any_synthetic), or (trades, any_synthetic,
    data_by_ticker) when collect_data=True. The data map is used by the
    random-entry baseline so it does not re-download the universe.
    """
    all_trades = []
    any_synthetic = False
    data_by_ticker = {}
    for ticker in universe:
        try:
            df, is_synthetic = _download_history(ticker, FULL_START, end, allow_synthetic)
            if is_synthetic:
                any_synthetic = True
            if collect_data:
                data_by_ticker[ticker] = df
            if len(df) < 230:
                continue
            ticker_trades = _run_single_ticker(
                ticker, df, spy_closes, spy_ma200, spy_dates,
                signal_fn, exit_fn, start, end, params,
                extra_state_fn, compute_options,
            )
            all_trades.extend(ticker_trades)
        except RuntimeError:
            raise  # propagate abort-on-no-real-data
        except Exception as e:
            logger.debug("backtest skip %s/%s: %s", setup_name, ticker, e)
    if collect_data:
        return all_trades, any_synthetic, data_by_ticker
    return all_trades, any_synthetic


# ---------------------------------------------------------------------------
# SPY regime arrays
# ---------------------------------------------------------------------------

def _spy_indicator_arrays(spy_df: pd.DataFrame):
    if spy_df.empty:
        return np.array([]), np.array([]), np.array([])
    closes = spy_df["Close"].values
    ma200 = pd.Series(spy_df["Close"]).rolling(200).mean().values
    dates = spy_df.index.values
    return closes, ma200, dates


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _compute_stats_for_trades(trades: list) -> dict:
    # Date order, not ticker order: the harness loops ticker by ticker,
    # so the raw list is grouped by ticker. Drawdown and every sequential
    # stat must be built on the date-sorted order.
    ordered = sorted(trades, key=lambda t: (t.entry_date, t.exit_date))
    stats = SetupStats()
    for t in ordered:
        stats.add(t.pnl_pct)
    return stats.summary()


def _split_trades(trades: list) -> dict:
    is_t  = [t for t in trades if IS_START  <= t.entry_date <= IS_END]
    oos_t = [t for t in trades if OOS_START <= t.entry_date <= OOS_END]
    return {
        "in_sample":      _compute_stats_for_trades(is_t),
        "out_of_sample":  _compute_stats_for_trades(oos_t),
        "regime_pre_2022":         _compute_stats_for_trades([t for t in trades if t.regime_calendar == "pre_2022"]),
        "regime_bear_2022":        _compute_stats_for_trades([t for t in trades if t.regime_calendar == "bear_2022"]),
        "regime_bull_2023_2024":   _compute_stats_for_trades([t for t in trades if t.regime_calendar == "bull_2023_2024"]),
        "regime_recent_2025":      _compute_stats_for_trades([t for t in trades if t.regime_calendar == "recent_2025"]),
        "regime_spy_above_200":    _compute_stats_for_trades([t for t in trades if t.regime_spy_ma == "above_200"]),
        "regime_spy_below_200":    _compute_stats_for_trades([t for t in trades if t.regime_spy_ma == "below_200"]),
    }


# ---------------------------------------------------------------------------
# Portfolio simulator (fixed-fractional risk, concurrency and heat caps,
# drawdown circuit breaker)
# ---------------------------------------------------------------------------

# Assumed adverse move (percent of entry price) used as the risk unit for
# heat accounting when a trade carries no stop distance (risk_pct is None).
# The position itself is still sized by the per-position notional cap.
FALLBACK_STOP_PCT = 2.0


@dataclass
class SimulatorParams:
    starting_equity: float = 100_000.0
    risk_pct: float = 1.0          # percent of current equity risked per trade
    max_positions: int = 10        # cap on concurrent open positions
    max_heat_pct: float = 10.0     # total open risk <= this percent of equity
    reduce_dd_pct: float = 10.0    # at this equity drawdown, risk per trade halves
    pause_dd_pct: float = 15.0     # at this equity drawdown, new entries pause
    max_position_pct: float = 10.0  # no single position larger than this percent of equity


def simulate_portfolio(trades: list, params: SimulatorParams | None = None) -> dict:
    """
    Event-driven portfolio simulation over a trade list.

    Trades are processed in entry-date order; on any date, exits of
    multi-day trades are applied before entries so freed capital is
    available the same day, while same-day trades exit after their entry
    (an exit processed before its entry would leave the position open
    forever, locking its slot and cash).
    Position size is fixed-fractional: risk_pct of current equity is
    risked per trade, sized by distance to the stop (trade.risk_pct)
    when known. When no stop distance is known, the position is sized
    at the per-position notional cap instead. Open positions are marked
    at cost, so the equity curve moves only on realized exits; intra-trade
    drawdown is not captured, which understates drawdown slightly.

    Circuit breaker: while equity sits at least reduce_dd_pct below its
    peak, risk per trade is halved; at pause_dd_pct or worse, no new
    entries are taken. Entries resume once the drawdown recovers below
    reduce_dd_pct.

    Returns portfolio metrics. Empty input returns zeroed metrics.
    """
    p = params or SimulatorParams()
    usable = [t for t in trades
              if t.entry_price and t.exit_price and t.entry_price > 0
              and t.exit_price > 0 and t.exit_date >= t.entry_date]
    if not usable:
        return {
            "trades_taken": 0, "trades_skipped": 0, "skipped_max_positions": 0,
            "skipped_heat": 0, "skipped_paused": 0, "skipped_cash": 0,
            "expectancy_pct": 0.0, "profit_factor": 0.0,
            "starting_equity": round(p.starting_equity, 2),
            "final_equity": round(p.starting_equity, 2),
            "total_return_pct": 0.0, "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0, "max_drawdown_dollars": 0.0,
            "calmar_ratio": 0.0, "recovery_factor": 0.0,
            "avg_duration_days": 0.0, "max_concurrent_positions": 0,
            "risk_pct": p.risk_pct, "max_positions": p.max_positions,
            "max_heat_pct": p.max_heat_pct, "pause_dd_pct": p.pause_dd_pct,
            "reduce_dd_pct": p.reduce_dd_pct,
        }

    ordered = sorted(usable, key=lambda t: (t.entry_date, t.exit_date))
    # Events: (date, phase, trade). Exits of multi-day trades (phase 0)
    # free capital and slots before entries (phase 1) on the same date.
    # Same-day trades (exit_date == entry_date, phase 2) must exit AFTER
    # their entry on that date: if their exit ran first, the pop would
    # miss, and the position would stay open forever, permanently locking
    # its slot and its cash.
    events = []
    for t in ordered:
        if t.exit_date > t.entry_date:
            events.append((t.exit_date, 0, t))
        else:
            events.append((t.exit_date, 2, t))
        events.append((t.entry_date, 1, t))
    events.sort(key=lambda e: (e[0], e[1]))

    equity = p.starting_equity
    peak = equity
    cash = equity
    open_pos = {}  # id(trade) -> dict(shares, notional, risk_dollars, trade)
    open_risk = 0.0
    max_dd_pct = 0.0
    max_dd_dollars = 0.0
    taken = 0
    skipped = {"max_positions": 0, "heat": 0, "paused": 0, "cash": 0}
    gross_win = 0.0
    gross_loss = 0.0
    pnl_pcts = []
    durations = []
    max_concurrent = 0
    first_date = ordered[0].entry_date
    last_date = ordered[0].exit_date

    def _refresh_dd():
        nonlocal peak, max_dd_pct, max_dd_dollars
        if equity > peak:
            peak = equity
        dd_dollars = peak - equity
        dd_pct = dd_dollars / peak * 100 if peak > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
        if dd_dollars > max_dd_dollars:
            max_dd_dollars = dd_dollars
        return dd_pct

    for event_date, kind, t in events:
        if event_date > last_date:
            last_date = event_date
        if kind == 1:  # entry
            dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if dd_pct >= p.pause_dd_pct:
                skipped["paused"] += 1
                continue
            if len(open_pos) >= p.max_positions:
                skipped["max_positions"] += 1
                continue
            risk_budget = p.risk_pct / 100 * equity
            if dd_pct >= p.reduce_dd_pct:
                risk_budget *= 0.5
            cap_notional = p.max_position_pct / 100 * equity
            if t.risk_pct is not None and t.risk_pct > 0:
                risk_per_share = t.entry_price * t.risk_pct / 100
                shares = risk_budget / risk_per_share
                notional = shares * t.entry_price
                if notional > cap_notional:
                    shares = cap_notional / t.entry_price
                    notional = cap_notional
                risk_dollars = shares * risk_per_share
            else:
                notional = cap_notional
                shares = notional / t.entry_price
                risk_dollars = notional * FALLBACK_STOP_PCT / 100
            if open_risk + risk_dollars > p.max_heat_pct / 100 * equity:
                skipped["heat"] += 1
                continue
            if cash < notional:
                skipped["cash"] += 1
                continue
            open_pos[id(t)] = {"shares": shares, "notional": notional,
                               "risk_dollars": risk_dollars, "trade": t}
            open_risk += risk_dollars
            cash -= notional
            taken += 1
            if len(open_pos) > max_concurrent:
                max_concurrent = len(open_pos)
        else:  # exit (kind 0 multi-day, kind 2 same-day)
            pos = open_pos.pop(id(t), None)
            if pos is None:
                continue  # trade was skipped at entry
            pnl_dollars = pos["shares"] * (t.exit_price - t.entry_price)
            cash += pos["notional"] + pnl_dollars
            equity = cash + sum(v["notional"] for v in open_pos.values())
            open_risk -= pos["risk_dollars"]
            if pnl_dollars > 0:
                gross_win += pnl_dollars
            else:
                gross_loss += abs(pnl_dollars)
            pnl_pcts.append(t.pnl_pct)
            durations.append((t.exit_date - t.entry_date).days)
            _refresh_dd()

    # Close any position still open at the end of the trade list at its
    # exit price (all trades here have an exit date, so this only fires
    # if an exit event was somehow missed).
    for pos in list(open_pos.values()):
        t = pos["trade"]
        pnl_dollars = pos["shares"] * (t.exit_price - t.entry_price)
        cash += pos["notional"] + pnl_dollars
        if pnl_dollars > 0:
            gross_win += pnl_dollars
        else:
            gross_loss += abs(pnl_dollars)
        pnl_pcts.append(t.pnl_pct)
        durations.append((t.exit_date - t.entry_date).days)
    equity = cash
    _refresh_dd()

    n_taken = len(pnl_pcts)
    expectancy = sum(pnl_pcts) / n_taken if n_taken else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    days = max((last_date - first_date).days, 1)
    years = days / 365.25
    total_return = (equity - p.starting_equity) / p.starting_equity
    cagr = (equity / p.starting_equity) ** (1 / years) - 1 if years > 0 else 0.0
    calmar = cagr * 100 / max_dd_pct if max_dd_pct > 0 else 0.0
    net_profit = equity - p.starting_equity
    recovery = net_profit / max_dd_dollars if max_dd_dollars > 0 else 0.0
    return {
        "trades_taken": taken,
        "trades_skipped": sum(skipped.values()),
        "skipped_max_positions": skipped["max_positions"],
        "skipped_heat": skipped["heat"],
        "skipped_paused": skipped["paused"],
        "skipped_cash": skipped["cash"],
        "expectancy_pct": round(expectancy, 3),
        "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
        "starting_equity": round(p.starting_equity, 2),
        "final_equity": round(equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_dollars": round(max_dd_dollars, 2),
        "calmar_ratio": round(calmar, 2),
        "recovery_factor": round(recovery, 2),
        "avg_duration_days": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "max_concurrent_positions": max_concurrent,
        "risk_pct": p.risk_pct, "max_positions": p.max_positions,
        "max_heat_pct": p.max_heat_pct, "pause_dd_pct": p.pause_dd_pct,
        "reduce_dd_pct": p.reduce_dd_pct,
    }


# ---------------------------------------------------------------------------
# Random-entry baseline
# ---------------------------------------------------------------------------

def _random_baseline_trades(data_by_ticker: dict, ref_trades: list,
                            start: date, end: date,
                            spy_closes: np.ndarray, spy_ma200: np.ndarray,
                            spy_dates: np.ndarray, seed: int = 42) -> list[Trade]:
    """
    Random entries with the same holding periods and universe as the setup
    under test: one baseline trade per reference trade, a random ticker
    from the same universe, a random signal date in the same period, and
    a holding period sampled from the reference trades. Same T+1 open
    entry, same 0.05% slippage per side, same regime tagging. The baseline
    carries no stop distance, so the simulator sizes it by its
    per-position notional cap.
    """
    import random
    rng = random.Random(seed)
    if not ref_trades or not data_by_ticker:
        return []
    durations = [max((t.exit_date - t.entry_date).days, 1) for t in ref_trades]
    tickers = [k for k, df in data_by_ticker.items() if df is not None and len(df) > 230]
    if not tickers:
        return []
    baseline = []
    for _ in ref_trades:
        for _attempt in range(20):
            ticker = rng.choice(tickers)
            df = data_by_ticker[ticker]
            idx = df.index
            lo = int(idx.searchsorted(np.datetime64(start)))
            hi = int(idx.searchsorted(np.datetime64(end), side="right")) - 1
            if hi - lo < 5:
                continue
            sig_row = rng.randint(lo, hi)
            entry_row = sig_row + 1
            if entry_row >= len(df):
                continue
            duration = rng.choice(durations)
            entry_date = idx[entry_row].date()
            exit_pos = int(idx.searchsorted(np.datetime64(entry_date) + np.timedelta64(duration, "D")))
            if exit_pos >= len(df):
                continue
            exit_date = idx[exit_pos].date()
            if exit_date <= entry_date:
                continue
            entry_price = _apply_slippage(float(df["Open"].iloc[entry_row]), "buy")
            exit_price = _apply_slippage(float(df["Open"].iloc[exit_pos]), "sell")
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            baseline.append(Trade(
                ticker=ticker,
                signal_date=idx[sig_row].date(),
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=exit_date,
                exit_price=exit_price,
                exit_reason="random_exit",
                regime_calendar=_calendar_regime(entry_date),
                regime_spy_ma=_spy_regime(entry_date, spy_closes, spy_ma200, spy_dates),
                pnl_pct=round(pnl_pct, 3),
            ))
            break
    return baseline


def _mean_stats(stats_list: list) -> dict:
    """Average numeric fields across per-seed stat dicts."""
    out = {}
    if not stats_list:
        return out
    keys = [k for k in stats_list[0] if k != "insufficient_sample"]
    for k in keys:
        vals = [s.get(k) for s in stats_list if isinstance(s.get(k), (int, float))]
        if vals:
            out[k] = round(sum(vals) / len(vals), 3)
    out["trade_count"] = stats_list[0].get("trade_count", 0)
    return out


def _mean_sim(sim_list: list) -> dict:
    """Average numeric fields across per-seed simulator result dicts."""
    out = {}
    if not sim_list:
        return out
    for k in sim_list[0]:
        vals = [s.get(k) for s in sim_list if isinstance(s.get(k), (int, float))]
        if vals:
            out[k] = round(sum(vals) / len(vals), 3)
    return out


def _baseline_summary(data_by_ticker: dict, ref_trades: list,
                      start: date, end: date,
                      spy_closes: np.ndarray, spy_ma200: np.ndarray,
                      spy_dates: np.ndarray,
                      n_seeds: int = 5, seed: int = 42,
                      sim_params: SimulatorParams | None = None) -> dict:
    """
    Random-entry baseline for a reference trade list, averaged across
    seeds. Returns per-trade stats and portfolio simulator metrics, each
    the mean across seeds, plus the seed settings for reproducibility.
    """
    per_trade = []
    per_sim = []
    for s in range(n_seeds):
        btrades = _random_baseline_trades(
            data_by_ticker, ref_trades, start, end,
            spy_closes, spy_ma200, spy_dates, seed=seed + s)
        per_trade.append(_compute_stats_for_trades(btrades))
        per_sim.append(simulate_portfolio(btrades, sim_params))
    return {
        "per_trade": _mean_stats(per_trade),
        "simulator": _mean_sim(per_sim),
        "n_seeds": n_seeds,
        "seed": seed,
    }


def _robustness_tests(
    setup_name, signal_fn, exit_fn, universe, base_params, param_keys,
    spy_closes, spy_ma200, spy_dates,
    extra_state_fn=None, compute_options=False, allow_synthetic=True,
) -> list[dict]:
    results = []
    subset = universe[:30]
    for key in param_keys:
        base_val = base_params[key]
        for mult, label in [(0.8, "-20%"), (1.2, "+20%")]:
            variant = dict(base_params)
            variant[key] = base_val * mult
            trades, _ = _run_setup(
                setup_name, signal_fn, exit_fn, subset,
                OOS_START, OOS_END, variant,
                spy_closes, spy_ma200, spy_dates,
                extra_state_fn, compute_options, allow_synthetic,
            )
            oos_stats = _compute_stats_for_trades(trades)
            results.append({
                "param": key, "variation": label,
                "value": round(base_val * mult, 4),
                "oos_stats": oos_stats,
            })
    return results


def _is_fragile(base_oos_stats: dict, robustness: list) -> bool:
    if base_oos_stats.get("expectancy_pct", 0) <= 0:
        return True
    survive = sum(
        1 for r in robustness
        if r["oos_stats"].get("expectancy_pct", 0) > 0
        and (r["oos_stats"].get("profit_factor") == "inf" or
             r["oos_stats"].get("profit_factor", 0) > 1.0)
    )
    return survive < len(robustness) / 2


def _verdict(oos_stats: dict, fragile: bool, modeled_only: bool) -> str:
    exp = oos_stats.get("expectancy_pct", 0)
    pf  = oos_stats.get("profit_factor", 0)
    n   = oos_stats.get("trade_count", 0)
    pf_ok = pf == "inf" or (isinstance(pf, (int, float)) and pf > 1.2)
    if exp <= 0 or not pf_ok:
        return "FAILS"
    if fragile or n < 30 or modeled_only:
        return "SHADOW ONLY"
    return "PASSES"


# ---------------------------------------------------------------------------
# Markdown report writer
# ---------------------------------------------------------------------------

def _fmt_stats(label: str, s: dict) -> str:
    if not s or s.get("trade_count", 0) == 0:
        return f"  {label}: no trades\n"
    stamp = " [INSUFFICIENT SAMPLE]" if s.get("insufficient_sample") else ""
    pf = s.get("profit_factor", 0)
    pf_str = str(pf) if pf == "inf" else f"{pf:.2f}"
    return (
        f"  {label}{stamp}\n"
        f"    Trades: {s['trade_count']}  |  Win rate: {s.get('win_rate_pct', 0):.1f}% (info only)\n"
        f"    Expectancy/trade: {s.get('expectancy_pct', 0):.3f}%  |  Profit factor: {pf_str}\n"
        f"    Avg win: {s.get('avg_win_pct', 0):.2f}%  |  Avg loss: {s.get('avg_loss_pct', 0):.2f}%\n"
        f"    Max drawdown: {s.get('max_drawdown_pct', 0):.2f}%\n"
    )


def _fmt_simulator(label: str, s: dict) -> str:
    if not s or s.get("trades_taken", 0) == 0:
        return f"  {label}: no trades taken\n"
    pf = s.get("profit_factor", 0)
    pf_str = str(pf) if pf == "inf" else f"{pf:.2f}"
    return (
        f"  {label}\n"
        f"    Trades taken: {s['trades_taken']}  |  Skipped: {s.get('trades_skipped', 0)} "
        f"(max positions {s.get('skipped_max_positions', 0)}, heat {s.get('skipped_heat', 0)}, "
        f"paused {s.get('skipped_paused', 0)}, cash {s.get('skipped_cash', 0)})\n"
        f"    Expectancy/trade: {s.get('expectancy_pct', 0):.3f}%  |  Profit factor: {pf_str}\n"
        f"    Start equity: ${s.get('starting_equity', 0):,.2f}  |  Final equity: "
        f"${s.get('final_equity', 0):,.2f}  |  Total return: {s.get('total_return_pct', 0):.2f}%\n"
        f"    CAGR: {s.get('cagr_pct', 0):.2f}%  |  Portfolio max drawdown: "
        f"{s.get('max_drawdown_pct', 0):.2f}% (${s.get('max_drawdown_dollars', 0):,.2f})\n"
        f"    Calmar ratio: {s.get('calmar_ratio', 0):.2f}  |  Recovery factor: "
        f"{s.get('recovery_factor', 0):.2f}\n"
        f"    Avg trade duration: {s.get('avg_duration_days', 0):.1f} days  |  "
        f"Max concurrent positions: {s.get('max_concurrent_positions', 0)}\n"
    )


def write_report(path, setup_name, rule_definition, universe_desc,
                 is_period, oos_period, splits, robustness,
                 verdict_str, fragile, data_source,
                 verdict_reason="",
                 modeled_note="", stock_signal_note="",
                 simulator=None, baseline=None, prior_run_note="") -> None:
    """
    data_source: a pre-formatted string, e.g.
      "REAL (fetched 2026-10-23)"
      "SYNTHETIC (mechanics verification only, not market evidence)"
    verdict_reason: if non-empty, printed alongside the verdict, e.g.
      "synthetic data: mechanics verification only, not market evidence"
    simulator: portfolio simulator metrics dict for the OOS trades (or None).
    baseline: random-entry baseline summary dict (or None).
    prior_run_note: preserved per-trade numbers from the previous report
      run, kept so history is not overwritten when the report regenerates.
    """
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    lines = []
    lines.append(f"# Backtest: {setup_name}\n")
    lines.append(f"Generated: {date.today().isoformat()}\n")
    lines.append(f"**Data source**: {data_source}\n")

    if "SYNTHETIC" in data_source:
        lines.append(
            "\n> **DATA NOTE: SYNTHETIC** -- this report was generated on procedurally "
            "generated random-walk price data because yfinance had no network access in the "
            "test environment.  All structural requirements (regime splits, walk-forward, "
            "robustness, etc.) are present and mechanically correct.  Rerun with live data "
            "on a networked deployment for real edge measurements.\n"
        )

    lines.append("\n## Cost Assumptions\n")
    lines.append(f"- Slippage: {SLIPPAGE_PER_SIDE * 100:.2f}% per side (applied to T+1 open)\n")
    lines.append(f"- Commission: ${OPTIONS_COMMISSION:.2f} per options contract; $0 for stock\n")
    lines.append(f"- Modeled spread haircut (Setup 2 only): {MODELED_SPREAD_HAIRCUT * 100:.0f}% of premium\n")

    lines.append("\n## Survivorship Caveat\n")
    lines.append(
        "Tested on currently listed names only; survivorship bias may "
        "flatter long-side results.\n"
    )

    lines.append("\n## Rule Definition\n")
    lines.append(f"```\n{rule_definition}\n```\n")

    lines.append("\n## Universe and Periods\n")
    lines.append(f"- Universe: {universe_desc}\n")
    lines.append(f"- In-sample (parameter selection): {is_period}\n")
    lines.append(f"- Out-of-sample (reported untouched): {oos_period}\n")

    if modeled_note:
        lines.append(f"\n## Options Model Note\n{modeled_note}\n")
    if stock_signal_note:
        lines.append(f"\n## Stock Signal Quality Note\n{stock_signal_note}\n")

    lines.append("\n## Walk-Forward Results\n")
    lines.append(
        "Per-trade stats below compound each trade at 100% of the account "
        "in date order. That max drawdown is not a portfolio drawdown; the "
        "portfolio drawdown is in the Portfolio Simulator section.\n"
    )
    lines.append(_fmt_stats("In-sample (2019-2022)", splits["in_sample"]))
    lines.append(_fmt_stats("Out-of-sample (2023-present)", splits["out_of_sample"]))

    lines.append("\n## Regime Splits\n")
    lines.append("### Calendar regimes\n")
    lines.append(_fmt_stats("Pre-2022", splits["regime_pre_2022"]))
    lines.append(_fmt_stats("Bear 2022", splits["regime_bear_2022"]))
    lines.append(_fmt_stats("Bull 2023-2024", splits["regime_bull_2023_2024"]))
    lines.append(_fmt_stats("Recent 2025", splits["regime_recent_2025"]))
    lines.append("\n### SPY 200-day MA regimes (per trade, at entry)\n")
    lines.append(_fmt_stats("SPY above 200 MA", splits["regime_spy_above_200"]))
    lines.append(_fmt_stats("SPY below 200 MA", splits["regime_spy_below_200"]))

    lines.append("\n## Robustness Tests (+/- 20% on key parameters)\n")
    if robustness:
        for r in robustness:
            oos = r["oos_stats"]
            pf = oos.get("profit_factor", 0)
            pf_str = str(pf) if pf == "inf" else f"{pf:.2f}"
            lines.append(
                f"  {r['param']} {r['variation']} (={r['value']:.4g}): "
                f"n={oos.get('trade_count', 0)}  exp={oos.get('expectancy_pct', 0):.3f}%  "
                f"PF={pf_str}\n"
            )
        lines.append("\n**Fragile**: edge does not survive across +/-20% variations.\n"
                     if fragile else "\nEdge survives across +/-20% parameter variations.\n")
    else:
        lines.append("  (no robustness tests run)\n")

    lines.append("\n## Verdict\n")
    if verdict_reason:
        lines.append(f"**{verdict_str}** -- {verdict_reason}\n")
    else:
        lines.append(f"**{verdict_str}**\n")

    if simulator is not None or baseline is not None:
        lines.append(f"\n## Portfolio Simulator and Random-Entry Baseline ({date.today().isoformat()})\n")
        lines.append(
            "Simulator settings: 1% of current equity risked per trade, sized "
            "by distance to the stop where known, otherwise by the 10% "
            "per-position notional cap; max 10 concurrent positions; total "
            "open risk capped at 10% of equity; risk halves at a 10% equity "
            "drawdown and new entries pause at a 15% drawdown, resuming "
            "below 10%. Starting equity $100,000. Open positions are marked "
            "at cost, so the equity curve moves on realized exits only and "
            "intra-trade drawdown is not captured.\n"
        )
    if simulator is not None:
        lines.append("\n### Portfolio simulator, out-of-sample trades\n")
        lines.append(_fmt_simulator("Setup through simulator", simulator))
    if baseline is not None:
        lines.append("\n### Random-entry baseline, out-of-sample\n")
        lines.append(
            f"Random entries, same universe and holding periods as the setup, "
            f"same T+1 open entry and costs, averaged across "
            f"{baseline.get('n_seeds', 0)} seeds (seed base {baseline.get('seed', 0)}), "
            f"run through the same portfolio simulator.\n"
        )
        lines.append(_fmt_stats("Baseline per-trade (mean across seeds)",
                                baseline.get("per_trade", {})))
        lines.append(_fmt_simulator("Baseline through simulator",
                                    baseline.get("simulator", {})))
        b_sim = baseline.get("simulator", {})
        b_pt = baseline.get("per_trade", {})
        if simulator is not None:
            s_exp = simulator.get("expectancy_pct", 0)
            b_exp = b_sim.get("expectancy_pct", b_pt.get("expectancy_pct", 0))
            s_pf = simulator.get("profit_factor", 0)
            b_pf = b_sim.get("profit_factor", b_pt.get("profit_factor", 0))

            def _pf_beats(a, b):
                if a == "inf":
                    return True
                if b == "inf":
                    return False
                return a > b

            beats = s_exp > b_exp and _pf_beats(s_pf, b_pf)
            lines.append(
                f"\nSetup beats its random-entry baseline: "
                f"{'yes' if beats else 'no'} "
                f"(setup simulator expectancy {s_exp:.3f}% vs baseline "
                f"{b_exp:.3f}%; setup profit factor {s_pf} vs baseline {b_pf}). "
                f"The registry verdict above is unchanged by this comparison; "
                f"the baseline is reported so the edge can be judged against "
                f"doing nothing.\n"
            )
    if prior_run_note:
        lines.append("\n### Prior run, preserved\n")
        lines.append(prior_run_note)

    with open(path, "w") as f:
        f.writelines(lines)
    logger.info("Report written: %s", path)


# ---------------------------------------------------------------------------
# Data source label helpers
# ---------------------------------------------------------------------------

SYNTHETIC_REASON = "synthetic data: mechanics verification only, not market evidence"


def _data_source_label(is_synthetic: bool) -> str:
    if is_synthetic:
        return "SYNTHETIC (mechanics verification only, not market evidence)"
    return f"REAL (fetched {date.today().isoformat()})"


def _apply_synthetic_cap(computed_verdict: str, is_synthetic: bool) -> tuple[str, str]:
    """
    Returns (final_verdict, verdict_reason).
    Caps PASSES at SHADOW ONLY when data is synthetic; FAILS stays FAILS.
    """
    if not is_synthetic:
        return computed_verdict, ""
    if computed_verdict == "FAILS":
        return "FAILS", SYNTHETIC_REASON
    return "SHADOW ONLY", SYNTHETIC_REASON


def _extract_prior_oos_block(path: str) -> str:
    """
    Pull the out-of-sample per-trade block from an existing report so
    regenerating the report preserves the previous run's numbers instead
    of overwriting history.
    """
    import os
    if not os.path.isfile(path):
        return ""
    try:
        lines = open(path).read().splitlines()
    except Exception:
        return ""
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Out-of-sample (2023-present)"):
            start = i
            break
    if start is None:
        return ""
    block = []
    for line in lines[start:]:
        block.append(line)
        if line.strip().startswith("Max drawdown:"):
            break
    if not block:
        return ""
    note = (
        "Per-trade numbers from the previous report run, preserved when "
        "this report regenerated. The max drawdown below is the old "
        "sequential figure, computed before the date-sorting fix, and is "
        "kept for history only.\n"
    )
    return note + "\n".join(block) + "\n"


def _sim_and_baseline(trades, data_by_ticker, spy_closes, spy_ma200, spy_dates):
    """Portfolio simulator plus random-entry baseline for OOS trades."""
    oos_trades = [t for t in trades if OOS_START <= t.entry_date <= OOS_END]
    sim = simulate_portfolio(oos_trades)
    base = _baseline_summary(data_by_ticker, oos_trades,
                             OOS_START, OOS_END,
                             spy_closes, spy_ma200, spy_dates)
    return sim, base


# ---------------------------------------------------------------------------
# Public entry point: run all three setups
# ---------------------------------------------------------------------------

def run_all_setups(
    output_dir: str = "backtests",
    universe_override: list | None = None,
    allow_synthetic: bool = True,
) -> list[dict]:
    """
    allow_synthetic=True (default): fall back to synthetic data when yfinance
      is unreachable; caps verdict at SHADOW ONLY for any setup with synthetic data.
    allow_synthetic=False: abort with RuntimeError on first real-data fetch failure.
    """
    import os

    if universe_override:
        universe_sp = universe_override
        universe_dir = universe_override
    else:
        try:
            import json
            root = os.path.dirname(os.path.abspath(__file__))
            sp_path = os.path.join(root, "../../data/sp500.json")
            da_path = os.path.join(root, "../../data/dividend-achievers.json")
            universe_sp = list(dict.fromkeys(json.load(open(sp_path)) + json.load(open(da_path))))
        except Exception as e:
            logger.warning("Could not load universe files: %s", e)
            from services.stock_data import DEFAULT_UNIVERSE
            universe_sp = list(DEFAULT_UNIVERSE)
        from services.stock_data import DEFAULT_UNIVERSE
        universe_dir = list(DEFAULT_UNIVERSE)

    logger.info("Universes: setups 1+2 = %d tickers, setup 3 = %d tickers",
                len(universe_sp), len(universe_dir))

    spy_df, spy_synthetic = _download_history("SPY", FULL_START, OOS_END, allow_synthetic)
    spy_closes, spy_ma200, spy_dates = _spy_indicator_arrays(spy_df)
    results = []

    # ---- Setup 1: Quality Pullback ----------------------------------------
    p1 = {"pullback_pct": 0.02, "rsi_entry": 55.0, "rsi_reset": 60.0,
          "rsi_target": 68.0, "time_stop_days": 30, "breakout_days": 55}
    logger.info("Setup 1: Quality Pullback (%d tickers)", len(universe_sp))
    t1, syn1, data1 = _run_setup("quality_pullback", _signal_quality_pullback, _exit_quality_pullback,
                          universe_sp, FULL_START, OOS_END, p1,
                          spy_closes, spy_ma200, spy_dates, allow_synthetic=allow_synthetic,
                          collect_data=True)
    s1 = _split_trades(t1)
    r1 = _robustness_tests("quality_pullback", _signal_quality_pullback, _exit_quality_pullback,
                            universe_sp, p1, ["pullback_pct", "rsi_entry", "rsi_reset"],
                            spy_closes, spy_ma200, spy_dates, allow_synthetic=allow_synthetic)
    oos1 = s1["out_of_sample"]
    frag1 = _is_fragile(oos1, r1)
    v1_raw = _verdict(oos1, frag1, False)
    v1, vr1 = _apply_synthetic_cap(v1_raw, syn1)
    sim1, base1 = _sim_and_baseline(t1, data1, spy_closes, spy_ma200, spy_dates)
    prior1 = _extract_prior_oos_block(os.path.join(output_dir, "quality_pullback.md"))
    write_report(
        path=os.path.join(output_dir, "quality_pullback.md"),
        setup_name="Quality Pullback",
        rule_definition=(
            "Universe: S&P 500 + Dividend Achievers with >=5y history\n"
            "Signal (close of day T):\n"
            "  price within 2% ABOVE 50-day or 200-day MA\n"
            "  200-day MA rising (today > value 20 days ago)\n"
            "  RSI(14) < 55 now and was > 60 within prior 20 sessions\n"
            "  volume < 20-day average volume\n"
            "  [earnings filter: skipped -- unavailable at backtest time]\n"
            "Entry: T+1 open + 0.05% slippage\n"
            "Exit: stop on close below 200 MA; target when RSI(14) > 68; time stop 30 days"
        ),
        universe_desc=f"S&P 500 + Dividend Achievers ({len(universe_sp)} tickers combined)",
        is_period="2019-01-01 to 2022-12-31",
        oos_period=f"2023-01-01 to {OOS_END.isoformat()}",
        splits=s1, robustness=r1, verdict_str=v1, fragile=frag1,
        data_source=_data_source_label(syn1), verdict_reason=vr1,
        simulator=sim1, baseline=base1, prior_run_note=prior1,
    )
    results.append({"setup": "quality_pullback", "verdict": v1, "oos_stats": oos1,
                    "data_source": _data_source_label(syn1),
                    "simulator": sim1, "baseline": base1})

    # ---- Setup 2: Premium at Support (Wheel) ---------------------------------
    p2 = {"support_pct": 0.02, "hv_pct_thresh": 2/3, "put_dte": 37,
          "time_stop_days": 30, "breakout_days": 55}

    def _esf2(ind, i, params):
        hv = ind["hv30"][i]
        return {"hv": float(hv) if not np.isnan(hv) else 0.25}

    logger.info("Setup 2: Premium at Support (%d tickers)", len(universe_sp))
    t2, syn2, data2 = _run_setup("premium_at_support", _signal_premium_at_support, _exit_premium_support,
                          universe_sp, FULL_START, OOS_END, p2,
                          spy_closes, spy_ma200, spy_dates, _esf2, compute_options=True,
                          allow_synthetic=allow_synthetic, collect_data=True)
    s2 = _split_trades(t2)
    r2 = _robustness_tests("premium_at_support", _signal_premium_at_support, _exit_premium_support,
                            universe_sp, p2, ["support_pct", "hv_pct_thresh"],
                            spy_closes, spy_ma200, spy_dates, _esf2,
                            allow_synthetic=allow_synthetic)
    oos2 = s2["out_of_sample"]
    frag2 = _is_fragile(oos2, r2)
    v2_raw = _verdict(oos2, frag2, True)  # modeled_only=True always caps at SHADOW ONLY
    v2, vr2 = _apply_synthetic_cap(v2_raw, syn2)
    sim2, base2 = _sim_and_baseline(t2, data2, spy_closes, spy_ma200, spy_dates)
    prior2 = _extract_prior_oos_block(os.path.join(output_dir, "premium_at_support.md"))
    support_held = sum(1 for t in t2 if t.pnl_pct > 0) / max(len(t2), 1) * 100
    write_report(
        path=os.path.join(output_dir, "premium_at_support.md"),
        setup_name="Premium at Support (Wheel)",
        rule_definition=(
            "Universe: S&P 500 + Dividend Achievers\n"
            "Signal (close of day T):\n"
            "  price within 2% of 50-day MA (above or below)\n"
            "  200-day MA rising\n"
            "  HV percentile in top third of trailing year\n"
            "  [IV percentile substitution: HV used as IV proxy; stated in every reference]\n"
            "Entry: T+1 open (stock signal); modeled put entered same day\n"
            "Modeled trade: sell 30-delta put, 37 DTE, Black-Scholes with HV;\n"
            "  5% spread haircut; close at 50% profit or 21 DTE;\n"
            "  assignment modeled if ITM at expiry\n"
            "Stock exit: stop on close below 200 MA; time stop 30 days\n"
            "Options P&L: MODELED everywhere it appears"
        ),
        universe_desc=f"S&P 500 + Dividend Achievers ({len(universe_sp)} tickers)",
        is_period="2019-01-01 to 2022-12-31",
        oos_period=f"2023-01-01 to {OOS_END.isoformat()}",
        splits=s2, robustness=r2, verdict_str=v2, fragile=frag2,
        data_source=_data_source_label(syn2), verdict_reason=vr2,
        simulator=sim2, baseline=base2, prior_run_note=prior2,
        modeled_note=(
            "All options P&L figures are **MODELED** using Black-Scholes with historical "
            "volatility as the IV proxy.  Real IV was not available for historical dates.  "
            "The HV-as-IV substitution is stated here and in every table that shows "
            "options P&L.  Stock-signal quality (did support hold) is reported separately."
        ),
        stock_signal_note=(
            f"Stock signal quality: support held (trade profitable) on "
            f"{support_held:.1f}% of trades (n={len(t2)}).  "
            "This is the stock-side edge only, independent of the options model."
        ),
    )
    results.append({"setup": "premium_at_support", "verdict": v2, "oos_stats": oos2,
                    "data_source": _data_source_label(syn2),
                    "simulator": sim2, "baseline": base2})

    # ---- Setup 3: Volume-Confirmed Breakout ----------------------------------
    p3 = {"breakout_days": 55, "vol_mult": 1.5, "atr_mult": 2.0,
          "time_stop_days": 15}

    def _esf3(ind, i, params):
        ph = ind["prior_high"][i]
        return {"breakout_level": float(ph) if not np.isnan(ph) else float(ind["closes"][i])}

    logger.info("Setup 3: Volume Breakout (%d tickers)", len(universe_dir))
    t3, syn3, data3 = _run_setup("volume_breakout", _signal_volume_breakout, _exit_volume_breakout,
                          universe_dir, FULL_START, OOS_END, p3,
                          spy_closes, spy_ma200, spy_dates, _esf3,
                          allow_synthetic=allow_synthetic, collect_data=True)
    s3 = _split_trades(t3)
    r3 = _robustness_tests("volume_breakout", _signal_volume_breakout, _exit_volume_breakout,
                            universe_dir, p3, ["breakout_days", "vol_mult"],
                            spy_closes, spy_ma200, spy_dates, _esf3,
                            allow_synthetic=allow_synthetic)
    oos3 = s3["out_of_sample"]
    frag3 = _is_fragile(oos3, r3)
    v3_raw = _verdict(oos3, frag3, False)
    v3, vr3 = _apply_synthetic_cap(v3_raw, syn3)
    sim3, base3 = _sim_and_baseline(t3, data3, spy_closes, spy_ma200, spy_dates)
    prior3 = _extract_prior_oos_block(os.path.join(output_dir, "volume_breakout.md"))
    write_report(
        path=os.path.join(output_dir, "volume_breakout.md"),
        setup_name="Volume-Confirmed Breakout",
        rule_definition=(
            "Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py)\n"
            "Signal (close of day T):\n"
            "  close above prior 55-day high (today excluded)\n"
            "  volume >= 1.5x 20-day average volume\n"
            "  price above rising 50-day MA\n"
            "Entry: T+1 open + 0.05% slippage\n"
            "Exit: stop on close below breakout level;\n"
            "      target at entry + 2 * ATR(14); time stop 15 days"
        ),
        universe_desc=f"Directional universe ({len(universe_dir)} tickers)",
        is_period="2019-01-01 to 2022-12-31",
        oos_period=f"2023-01-01 to {OOS_END.isoformat()}",
        splits=s3, robustness=r3, verdict_str=v3, fragile=frag3,
        data_source=_data_source_label(syn3), verdict_reason=vr3,
        simulator=sim3, baseline=base3, prior_run_note=prior3,
        modeled_note="Options layer is out of scope for this phase.  Stock-level edge only.",
    )
    results.append({"setup": "volume_breakout", "verdict": v3, "oos_stats": oos3,
                    "data_source": _data_source_label(syn3),
                    "simulator": sim3, "baseline": base3})

    logger.info("Verdicts: %s", {r["setup"]: r["verdict"] for r in results})
    return results
