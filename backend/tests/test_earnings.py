"""Tests for the composite earnings resolver (services/earnings.py).

The resolver tries FMP, Polygon, Yahoo and Finnhub in order and
takes the first future date found. Each source is individually
guarded, so one dead feed never blocks the others, and a missing
API key skips that source silently. These tests pin the order, the
failover, and the all-fail result, with stubbed sources; no network
is used.
"""

import sys
import types
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import earnings as earn


def _future(days):
    return date.today() + timedelta(days=days)


def test_first_hit_wins():
    legs = [("fmp", lambda t: _future(101)),
            ("polygon", lambda t: _future(110)),
            ("yahoo", lambda t: _future(120)),
            ("finnhub", lambda t: _future(130))]
    # Monkeypatch the source table itself: _SOURCES holds the
    # original function objects, so patching the leg names alone
    # would not change the order the resolver walks.
    import services.earnings as mod
    old = mod._SOURCES
    mod._SOURCES = tuple(legs)
    try:
        found, source = mod.resolve_next_earnings("ZETA")
    finally:
        mod._SOURCES = old
    assert found == _future(101)
    assert source == "fmp"


def test_each_source_failing_in_turn():
    def _boom(t):
        raise RuntimeError("feed down")

    legs = [("fmp", _boom),
            ("polygon", lambda t: None),
            ("yahoo", _boom),
            ("finnhub", lambda t: _future(101))]
    import services.earnings as mod
    old = mod._SOURCES
    mod._SOURCES = tuple(legs)
    try:
        found, source = mod.resolve_next_earnings("ZETA")
    finally:
        mod._SOURCES = old
    assert found == _future(101)
    assert source == "finnhub"


def test_all_fail_returns_none():
    def _boom(t):
        raise RuntimeError("feed down")

    legs = [("fmp", _boom),
            ("polygon", lambda t: None),
            ("yahoo", lambda t: None),
            ("finnhub", lambda t: None)]
    import services.earnings as mod
    old = mod._SOURCES
    mod._SOURCES = tuple(legs)
    try:
        found, source = mod.resolve_next_earnings("ZETA")
    finally:
        mod._SOURCES = old
    assert found is None
    assert source is None


def test_empty_ticker_returns_none():
    assert earn.resolve_next_earnings("") == (None, None)
    assert earn.resolve_next_earnings(None) == (None, None)


def test_future_dates_drops_past_and_keeps_today():
    out = earn._future_dates([_future(-5), _future(0), _future(10)])
    assert out == [_future(0), _future(10)]
    assert earn._future_dates([None, "not-a-date"]) == []


def test_from_fmp_parses_rows(monkeypatch):
    import services.fmp_client as fmp

    monkeypatch.setattr(
        fmp, "_get",
        lambda path, params=None, timeout=15: [
            {"date": "2027-02-22", "symbol": "ZETA"},
            {"date": "2026-11-05", "symbol": "ZETA"},
        ])
    assert earn._from_fmp("ZETA") == date(2027, 2, 22)


def test_from_fmp_past_only_and_non_list(monkeypatch):
    import services.fmp_client as fmp

    monkeypatch.setattr(
        fmp, "_get",
        lambda path, params=None, timeout=15: [
            {"date": "2026-11-05", "symbol": "ZETA"},
        ])
    assert earn._from_fmp("ZETA") is None
    monkeypatch.setattr(
        fmp, "_get",
        lambda path, params=None, timeout=15: {"Error Message": "bad key"})
    assert earn._from_fmp("ZETA") is None
    monkeypatch.setattr(fmp, "_get", lambda *a, **k: None)
    assert earn._from_fmp("ZETA") is None


def test_from_finnhub_converts_days(monkeypatch):
    # The finnhub package is not installed in the sandbox, so stub
    # it in sys.modules before importing the client; the test
    # monkeypatches get_earnings_within itself, so the fake client
    # is never called.
    fake = types.ModuleType("finnhub")
    fake.Client = object
    monkeypatch.setitem(sys.modules, "finnhub", fake)
    import services.finnhub_client as fh

    monkeypatch.setattr(fh, "get_earnings_within",
                        lambda symbol, days=120: 101)
    assert earn._from_finnhub("ZETA") == _future(101)
    monkeypatch.setattr(fh, "get_earnings_within",
                        lambda symbol, days=120: None)
    assert earn._from_finnhub("ZETA") is None


def test_polygon_leg_yields_nothing():
    assert earn._from_polygon("ZETA") is None


class _FakeFrame:
    def __init__(self, dates):
        self.index = dates
        self.empty = len(dates) == 0


class _FakeTicker:
    def __init__(self, dates=None, calendar=None):
        self._dates = dates
        self._calendar = calendar

    def get_earnings_dates(self, limit=8):
        return _FakeFrame(self._dates or [])

    @property
    def calendar(self):
        return self._calendar


def _install_fake_yfinance(monkeypatch, dates=None, calendar=None):
    mod = types.ModuleType("yfinance")
    mod.Ticker = lambda t: _FakeTicker(dates, calendar)
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def test_from_yahoo_dates_table(monkeypatch):
    _install_fake_yfinance(monkeypatch, dates=[_future(-90), _future(101)])
    assert earn._from_yahoo("ZETA") == _future(101)


def test_from_yahoo_calendar_fallback(monkeypatch):
    _install_fake_yfinance(
        monkeypatch, dates=[],
        calendar={"Earnings Date": [_future(45)]})
    assert earn._from_yahoo("ZETA") == _future(45)


def test_from_yahoo_nothing(monkeypatch):
    _install_fake_yfinance(monkeypatch, dates=[], calendar={})
    assert earn._from_yahoo("ZETA") is None
