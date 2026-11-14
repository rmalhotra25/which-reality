"""Tests for the alert engine indicators NaN-row fix.

Yahoo returns a NaN row for the current day when the session has
not settled yet (after hours, or before the first print). The
indicators must drop that row and use the last settled close, or
the price reads as no price available and the Answer block and the
company snapshot show no price. No network is used; the DataFrame
is built by hand.
"""

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.alert_engine import _indicators


def _ohlcv(days=220, last_nan=True):
    """220 settled sessions plus, by default, one trailing NaN row."""
    idx = pd.date_range("2026-01-05", periods=days, freq="B")
    closes = [100.0 + i * 0.1 for i in range(days)]
    df = pd.DataFrame({
        "Open": [c - 0.5 for c in closes],
        "High": [c + 0.5 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1000] * days,
    }, index=idx)
    if last_nan:
        nan_row = pd.DataFrame({
            "Open": [float("nan")],
            "High": [float("nan")],
            "Low": [float("nan")],
            "Close": [float("nan")],
            "Volume": [float("nan")],
        }, index=[idx[-1] + pd.Timedelta(days=1)])
        df = pd.concat([df, nan_row])
    return df


def test_trailing_nan_row_uses_last_settled_close():
    ind = _indicators(_ohlcv(last_nan=True))
    assert ind is not None
    assert ind["price"] == 100.0 + 219 * 0.1
    assert not math.isnan(ind["price"])
    assert ind["ma50"] is not None
    assert ind["ma200"] is not None


def test_no_nan_row_returns_same_price():
    ind = _indicators(_ohlcv(last_nan=False))
    assert ind is not None
    assert ind["price"] == 100.0 + 219 * 0.1


def test_all_nan_returns_none():
    df = pd.DataFrame({
        "Open": [float("nan")] * 220,
        "High": [float("nan")] * 220,
        "Low": [float("nan")] * 220,
        "Close": [float("nan")] * 220,
        "Volume": [float("nan")] * 220,
    }, index=pd.date_range("2026-01-05", periods=220, freq="B"))
    assert _indicators(df) is None


def test_no_em_dash_in_fix_comment():
    src = Path(__file__).resolve().parents[1] / "services" / "alert_engine.py"
    text = src.read_text()
    assert "—" not in text
