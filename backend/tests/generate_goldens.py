"""
Phase 4 Step 1 -- generate golden output files by running current tiers code with fixtures.

Run once from backend/ dir:
    python tests/generate_goldens.py

Writes:
  tests/goldens/{put_tiers,call_tiers,weekly_call_tiers}_{TICKER}_{path}.json
  where path is "polygon" or "yfinance".
"""

import json
import sys
import os
import unittest.mock as mock
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
GOLDENS = os.path.join(os.path.dirname(__file__), "goldens")
TICKERS = ["MSFT", "AAPL", "SPY"]
ANCHOR_DATE = date(2026, 10, 23)


# ---------------------------------------------------------------------------
# Helpers to load fixtures
# ---------------------------------------------------------------------------

def load_polygon_fixture(ticker: str, contract_type: str) -> dict:
    key = ticker if ticker != "MSFT" else ""
    if key:
        fname = f"polygon_chain_{ticker}_{contract_type}.json"
    else:
        fname = f"polygon_chain_{contract_type}.json"
    with open(os.path.join(FIXTURES, fname)) as f:
        return json.load(f)


def load_yf_fixture(ticker: str) -> dict:
    with open(os.path.join(FIXTURES, f"yf_chain_{ticker}.json")) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Mock yf.Ticker based on yfinance fixture
# ---------------------------------------------------------------------------

def make_mock_ticker(yf_data: dict):
    """Return a mock yf.Ticker instance using fixture data."""
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

        def option_chain(self, expiry):
            chain_data = yf_data["chains"].get(expiry, {"calls": [], "puts": []})
            return MockOptionChain(
                calls_df=pd.DataFrame(chain_data["calls"]),
                puts_df=pd.DataFrame(chain_data["puts"]),
            )

    return MockTicker()


# ---------------------------------------------------------------------------
# Mock date.today()
# ---------------------------------------------------------------------------

def make_mock_date():
    """Return a date subclass whose today() returns ANCHOR_DATE."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return ANCHOR_DATE

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return _FixedDate


# ---------------------------------------------------------------------------
# Run tiers with Polygon fixture (primary path)
# ---------------------------------------------------------------------------

def run_polygon_path(func_name: str, ticker: str, contract_type: str) -> dict | None:
    """Run a tiers function using the Polygon fixture (mocks _polygon_options_chain)."""
    from services.stock_data import StockDataService

    poly_data = load_polygon_fixture(ticker, contract_type)
    yf_data = load_yf_fixture(ticker)
    rows = poly_data["rows"]
    price = poly_data["price"]

    mock_ticker = make_mock_ticker(yf_data)
    FixedDate = make_mock_date()

    def mock_polygon_chain(self, tkr, ctype, dte_min, dte_max, near_price=None):
        # Return all rows; filter by dte_min/dte_max using the anchor date
        filtered = [
            r for r in rows
            if dte_min <= r["dte"] <= dte_max
        ]
        return filtered, price

    with mock.patch.object(StockDataService, "_polygon_options_chain", mock_polygon_chain), \
         mock.patch("services.stock_data.yf") as mock_yf, \
         mock.patch("services.stock_data.date", FixedDate):
        mock_yf.Ticker.return_value = mock_ticker
        svc = StockDataService()
        fn = getattr(svc, func_name)
        return fn(ticker)


# ---------------------------------------------------------------------------
# Run tiers with yfinance fixture (fallback path)
# ---------------------------------------------------------------------------

def run_yfinance_path(func_name: str, ticker: str) -> dict | None:
    """Run a tiers function using the yfinance fixture (forces Polygon to return empty)."""
    from services.stock_data import StockDataService

    yf_data = load_yf_fixture(ticker)
    mock_ticker = make_mock_ticker(yf_data)
    FixedDate = make_mock_date()

    def mock_polygon_empty(self, tkr, ctype, dte_min, dte_max, near_price=None):
        return [], None

    with mock.patch.object(StockDataService, "_polygon_options_chain", mock_polygon_empty), \
         mock.patch("services.stock_data.yf") as mock_yf, \
         mock.patch("services.stock_data.date", FixedDate):
        mock_yf.Ticker.return_value = mock_ticker
        mock_yf.Ticker.side_effect = lambda t: mock_ticker
        svc = StockDataService()
        fn = getattr(svc, func_name)
        return fn(ticker)


# ---------------------------------------------------------------------------
# Generate all goldens
# ---------------------------------------------------------------------------

def main():
    os.makedirs(GOLDENS, exist_ok=True)

    cases = [
        # (func_name, contract_type_for_polygon_fixture)
        ("get_put_tiers", "put"),
        ("get_call_tiers", "call"),
        ("get_weekly_call_tiers", "call"),
    ]

    for ticker in TICKERS:
        for func_name, ctype in cases:
            print(f"{ticker} {func_name}...")

            # Polygon path golden
            try:
                result = run_polygon_path(func_name, ticker, ctype)
                fname = f"{func_name}_{ticker}_polygon.json"
                with open(os.path.join(GOLDENS, fname), "w") as f:
                    json.dump(result, f, indent=2)
                status = "OK" if result else "None"
                print(f"  polygon -> {fname} [{status}]")
            except Exception as e:
                print(f"  polygon ERROR: {e}")
                import traceback; traceback.print_exc()

            # yfinance path golden
            try:
                result = run_yfinance_path(func_name, ticker)
                fname = f"{func_name}_{ticker}_yfinance.json"
                with open(os.path.join(GOLDENS, fname), "w") as f:
                    json.dump(result, f, indent=2)
                status = "OK" if result else "None"
                print(f"  yfinance -> {fname} [{status}]")
            except Exception as e:
                print(f"  yfinance ERROR: {e}")
                import traceback; traceback.print_exc()

    print("\nGolden generation complete.")


if __name__ == "__main__":
    main()
