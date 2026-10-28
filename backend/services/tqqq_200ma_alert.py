"""
TQQQ call-window alert: QQQ 200-day MA touch evaluator.

Purpose: alert (never auto-trade) when TQQQ calls are "in the window"
under the QQQ 200DMA framework -- i.e. QQQ has pulled back to a rising
200-day moving average and held it into the close. This is a CONDITION
alert, not a buy recommendation and not a validated setup.

Status is SHADOW by design. The companion backtest
(scripts/backtest_tqqq_200ma.py) found, on the stock side only:
  - Fixed 10-day hold: -5.63% expectancy/trade, profit factor 0.51
    (17 trades, 2010-2026).
  - Reclaim-or-stop variant: -0.77% expectancy/trade, PF 0.79.
  - Out-of-sample positive on all variants but on 2-3 trades each
    (noise, not evidence).
The options layer (TQQQ calls) is untested: theta decay and implied
volatility sit on top of an already negative-expectancy stock signal.
Any alert this module emits must carry that record with it.

Signal definition (identical to the backtest, day T from closes only):
  - QQQ 200DMA rising (above its value 20 sessions ago).
  - QQQ above its 200DMA at the prior close.
  - Day-T low touches or dips below the 200DMA, day-T close back above it.
Unlike the backtest, the alert uses the MOST RECENT raw touch (no
20-session cooldown): the alert answers "is QQQ at the line now?", while
the backtest used a cooldown to avoid overlapping positions.

Alert states (evaluated on the latest closed session):
  OPEN        -- a signal fired within the last `window_sessions`
                 sessions and QQQ has not closed below the 200DMA since.
                 The call window is open; guardrails apply.
  INVALIDATED -- a signal fired, but QQQ has since closed below the
                 200DMA. The thesis is dead; the window is closed.
  EXPIRED     -- a signal fired but the window has passed with no
                 invalidation. Price moved away from the line.
  NO_SIGNAL   -- no qualifying touch in the available history.

This module is pure evaluation: no I/O, no database, no network. It
takes aligned QQQ/TQQQ DataFrames (DatetimeIndex, Open/High/Low/Close)
and returns a dict shaped like the alert engine's alert records.

Reconciliation note (current master): the app now enforces a P1 alert
contract (services/alert_contract.py) and a rule registry
(models/rule_registry.py). A rule that is not in the registry cannot
fire or notify, and an alert that lacks the contract fields -- an
imperative action, entry_price with its source, a computed size (or
suppression when no stop distance exists to size from), an expiry
date, a reason with fired values, rule_key, setup_status -- is
suppressed at build time and never reaches the Alerts tab or
Telegram. This window alert, as designed, carries no entry, no size,
and no expiry (it marks a condition, not a trade), so it would be
suppressed if wired into the engine as-is. It therefore stays a
standalone runner output (scripts/check_tqqq_200ma_alert.py) until it
is reframed with a concrete entry, stop-derived size, and expiry, plus
a RuleRegistry row (trigger_json thresholds, action_template,
size_rule, invalidation, expiry, cooldown, dedupe_key_format,
source_function). Note the engine's evaluators are single-ticker;
this signal needs a QQQ/TQQQ pair, which is a second reason it ships
standalone first.

Timing note: the signal needs the day-T CLOSE, so this alert can only
fire after the close. An intraday dip below the line is not an alert
until the close holds above it. The natural home is the 17:30 ET
post-close alert job.
"""

SETUP_KEY = "tqqq_200ma_call_window"
SETUP_NAME = "TQQQ Call Window (QQQ 200DMA)"
SETUP_STATUS = "SHADOW"  # Never LIVE: backtest verdict is not PASSES.
WINDOW_SESSIONS = 5

BACKTEST_NOTE = (
    "Backtest record (stock side only, scripts/backtest_tqqq_200ma.py): "
    "17 trades 2010-2026; fixed 10-day hold -5.63%/trade, PF 0.51; "
    "reclaim-or-stop variant -0.77%/trade, PF 0.79; out-of-sample positive "
    "on 2-3 trades only. TQQQ calls are UNTESTED on top of this signal "
    "(theta + IV). This alert marks a window, not a validated setup."
)

STRUCTURE_TEMPLATE = (
    "If trading this window at all: defined-risk TQQQ call spread only "
    "(buy a near-the-money call, sell a further out-of-the-money call), "
    "30-60 days to expiry, small size. No specific strikes or premiums "
    "are given by this alert -- check the live chain. Naked long TQQQ "
    "calls are not recommended: high IV plus daily-reset decay means a "
    "slow or small bounce loses even if direction is right."
)


def _signals(closes, lows, ma200):
    """Indices of touch-and-hold signals. Pure function of closes/lows."""
    import numpy as np

    out = []
    for i in range(200, len(closes)):
        if np.isnan(ma200[i]) or np.isnan(ma200[i - 20]):
            continue
        rising = ma200[i] > ma200[i - 20]
        was_above = closes[i - 1] >= ma200[i - 1]
        touched = lows[i] <= ma200[i]
        held = closes[i] >= ma200[i]
        if rising and was_above and touched and held:
            out.append(i)
    return out


def evaluate(qqq_df, tqqq_df, window_sessions=WINDOW_SESSIONS):
    """Evaluate the call window on the latest closed session.

    Returns a dict with at least: state, setup_key, setup_name,
    setup_status, ticker, as_of, last_signal_date, and -- for OPEN --
    the levels, invalidation, and guardrails. Returns None only when
    there is not enough history to compute a 200DMA.
    """
    import numpy as np
    import pandas as pd

    if len(qqq_df) < 221 or len(tqqq_df) < 221:
        return None
    joined = qqq_df.join(tqqq_df, lsuffix="_qqq", rsuffix="_tqqq", how="inner")
    if len(joined) < 221:
        return None
    closes = joined["Close_qqq"].to_numpy(dtype=float)
    lows = joined["Low_qqq"].to_numpy(dtype=float)
    dates = joined.index
    ma200 = pd.Series(closes).rolling(200).mean().to_numpy(dtype=float)
    tqqq_close = float(joined["Close_tqqq"].iloc[-1])

    sigs = _signals(closes, lows, ma200)
    base = {
        "setup_key": SETUP_KEY,
        "setup_name": SETUP_NAME,
        "setup_status": SETUP_STATUS,
        "ticker": "TQQQ",
        "as_of": dates[-1].date().isoformat(),
        "tqqq_close": round(tqqq_close, 2),
        "qqq_200dma": round(float(ma200[-1]), 2),
        "backtest_note": BACKTEST_NOTE,
    }
    if not sigs:
        return {**base, "state": "NO_SIGNAL", "last_signal_date": None,
                "detail": "No qualifying QQQ 200DMA touch in history."}

    s = sigs[-1]
    last_signal = dates[s].date().isoformat()
    # Invalidation: any close below the 200DMA after the signal day.
    invalid_idx = None
    for j in range(s + 1, len(closes)):
        if closes[j] < ma200[j]:
            invalid_idx = j
            break
    if invalid_idx is not None:
        return {
            **base, "state": "INVALIDATED", "last_signal_date": last_signal,
            "invalidation_date": dates[invalid_idx].date().isoformat(),
            "detail": ("QQQ closed below its 200DMA after the signal "
                       "(thesis dead; window closed)."),
        }
    sessions_since = (len(closes) - 1) - s
    if sessions_since > window_sessions:
        return {
            **base, "state": "EXPIRED", "last_signal_date": last_signal,
            "sessions_since_signal": int(sessions_since),
            "detail": ("Last touch was %d sessions ago; price moved away "
                       "from the line." % sessions_since),
        }
    qqq_close = float(closes[-1])
    return {
        **base,
        "state": "OPEN",
        "last_signal_date": last_signal,
        "sessions_since_signal": int(sessions_since),
        "qqq_close": round(qqq_close, 2),
        "qqq_vs_200dma_pct": round((qqq_close / float(ma200[-1]) - 1.0) * 100, 2),
        "action": "CALL_WINDOW_OPEN",
        "action_summary": (
            "TQQQ call window OPEN: QQQ touched a rising 200DMA on "
            f"{last_signal} and has held it since. This is a window "
            "alert, not a buy recommendation -- see backtest_note."
        ),
        "invalidation_price": round(float(ma200[-1]), 2),
        "invalidation_text": (
            "Invalidated if QQQ closes below its 200DMA "
            f"(currently ${float(ma200[-1]):.2f}). On invalidation, "
            "the window closes; do not add."
        ),
        "structure_template": STRUCTURE_TEMPLATE,
        "conditions": {
            "qqq_200dma_rising": True,
            "signal_date": last_signal,
            "sessions_since_signal": int(sessions_since),
        },
    }
