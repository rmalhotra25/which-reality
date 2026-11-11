"""Tests for the Finnhub earnings window used by the Story display.

The alert engine's earnings gate keeps the 30-day window through
get_earnings_this_month, so a missing feed still blocks a setup.
The Story display uses the wider 120-day window so a next earnings
date a quarter out (a name that reported this month) still shows
instead of reading unknown.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("finnhub")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.finnhub_client import (  # noqa: E402
    get_earnings_this_month,
    get_earnings_within,
)


class _FakeClient:
    def __init__(self, dates):
        self._dates = dates

    def earnings_calendar(self, _from, to, symbol):
        return {"earningsCalendar": [{"date": d} for d in self._dates
                                     if d <= to]}


def test_earnings_within_finds_a_quarter_out(monkeypatch):
    import services.finnhub_client as fh

    future = (date.today() + timedelta(days=90)).isoformat()
    monkeypatch.setattr(fh, "_get_client", lambda: _FakeClient([future]))
    assert get_earnings_within("PLTR", days=120) == 90
    assert get_earnings_this_month("PLTR") is None


def test_earnings_within_returns_none_when_empty(monkeypatch):
    import services.finnhub_client as fh

    monkeypatch.setattr(fh, "_get_client", lambda: _FakeClient([]))
    assert get_earnings_within("PLTR", days=120) is None
