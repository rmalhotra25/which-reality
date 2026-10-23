"""
Phase 4 regression tests.

Each test drives a tiers function with a fixed fixture payload and asserts the output
matches the golden file. Zero diffs = the refactoring is safe.

Run from backend/ dir:
    pytest tests/test_tiers_regression.py -v

Fixtures and goldens live in tests/fixtures/ and tests/goldens/.
To regenerate goldens after an APPROVED change: python tests/generate_goldens.py
"""

import json
import os
import unittest.mock as mock
from datetime import date

import pytest

from services.chain_provider import ChainProvider

TESTS_DIR = os.path.dirname(__file__)
FIXTURES = os.path.join(TESTS_DIR, "fixtures")
GOLDENS = os.path.join(TESTS_DIR, "goldens")
ANCHOR_DATE = date(2026, 10, 23)

# All cases: (ticker, func_name, polygon_contract_type)
TIERS_CASES = [
    ("MSFT", "get_put_tiers", "put"),
    ("MSFT", "get_call_tiers", "call"),
    ("MSFT", "get_weekly_call_tiers", "call"),
    ("AAPL", "get_put_tiers", "put"),
    ("AAPL", "get_call_tiers", "call"),
    ("AAPL", "get_weekly_call_tiers", "call"),
    ("SPY", "get_put_tiers", "put"),
    ("SPY", "get_call_tiers", "call"),
    ("SPY", "get_weekly_call_tiers", "call"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_fixture(fname: str) -> dict:
    with open(os.path.join(FIXTURES, fname)) as f:
        return json.load(f)


def load_golden(fname: str) -> dict | None:
    path = os.path.join(GOLDENS, fname)
    if not os.path.exists(path):
        pytest.fail(f"Golden file missing: {path}. Run: python tests/generate_goldens.py")
    with open(path) as f:
        return json.load(f)


def load_polygon_fixture(ticker: str, contract_type: str) -> dict:
    fname = f"polygon_chain_{ticker}_{contract_type}.json" if ticker != "MSFT" else f"polygon_chain_{contract_type}.json"
    return load_fixture(fname)


def load_yf_fixture(ticker: str) -> dict:
    return load_fixture(f"yf_chain_{ticker}.json")


def make_mock_ticker(yf_data: dict):
    """Build a minimal yf.Ticker mock from fixture data."""
    import pandas as pd

    price = yf_data["price"]

    class MockFastInfo:
        last_price = price
        previous_close = yf_data["fast_info"]["previous_close"]

    class MockOptionChain:
        def __init__(self, calls_df, puts_df):
            self.calls = calls_df
            self.puts = puts_df

    class MockTicker:
        fast_info = MockFastInfo()
        options = yf_data["options"]
        info = yf_data.get("info", {})

        def option_chain(self_, expiry):
            chain_data = yf_data["chains"].get(expiry, {"calls": [], "puts": []})
            return MockOptionChain(
                calls_df=pd.DataFrame(chain_data["calls"]),
                puts_df=pd.DataFrame(chain_data["puts"]),
            )

    return MockTicker()


def make_fixed_date():
    """Return a date subclass whose today() always returns ANCHOR_DATE."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return ANCHOR_DATE

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return _FixedDate


# ---------------------------------------------------------------------------
# Test fixtures (pytest fixtures, not data fixtures)
# ---------------------------------------------------------------------------

@pytest.fixture
def fixed_date():
    return make_fixed_date()


# ---------------------------------------------------------------------------
# Polygon-path regression tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,func_name,ctype", TIERS_CASES)
def test_polygon_path(ticker, func_name, ctype, fixed_date):
    from services.stock_data import StockDataService

    poly_data = load_polygon_fixture(ticker, ctype)
    yf_data = load_yf_fixture(ticker)
    rows = poly_data["rows"]
    price = poly_data["price"]

    golden_fname = f"{func_name}_{ticker}_polygon.json"
    golden = load_golden(golden_fname)

    mock_ticker = make_mock_ticker(yf_data)

    def mock_polygon_rows(self, tkr, ctype_arg, dte_min, dte_max, near_price=None):
        filtered = [r for r in rows if dte_min <= r["dte"] <= dte_max]
        return filtered, price if filtered else ([], None)

    with mock.patch.object(ChainProvider, "_fetch_polygon_rows", mock_polygon_rows), \
         mock.patch("services.chain_provider.yf") as mock_yf, \
         mock.patch("services.chain_provider.date", fixed_date):
        mock_yf.Ticker.side_effect = lambda t: mock_ticker
        svc = StockDataService()
        result = getattr(svc, func_name)(ticker)

    assert result == golden, (
        f"{ticker} {func_name} polygon path: result differs from golden.\n"
        f"Result: {json.dumps(result, indent=2)}\n"
        f"Golden: {json.dumps(golden, indent=2)}"
    )


# ---------------------------------------------------------------------------
# yfinance-path regression tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,func_name,ctype", TIERS_CASES)
def test_yfinance_path(ticker, func_name, ctype, fixed_date):
    from services.stock_data import StockDataService

    yf_data = load_yf_fixture(ticker)
    golden_fname = f"{func_name}_{ticker}_yfinance.json"
    golden = load_golden(golden_fname)

    mock_ticker = make_mock_ticker(yf_data)

    def mock_polygon_empty(self, tkr, ctype_arg, dte_min, dte_max, near_price=None):
        return [], None

    with mock.patch.object(ChainProvider, "_fetch_polygon_rows", mock_polygon_empty), \
         mock.patch("services.chain_provider.yf") as mock_yf, \
         mock.patch("services.chain_provider.date", fixed_date):
        mock_yf.Ticker.side_effect = lambda t: mock_ticker
        svc = StockDataService()
        result = getattr(svc, func_name)(ticker)

    assert result == golden, (
        f"{ticker} {func_name} yfinance path: result differs from golden.\n"
        f"Result: {json.dumps(result, indent=2)}\n"
        f"Golden: {json.dumps(golden, indent=2)}"
    )
