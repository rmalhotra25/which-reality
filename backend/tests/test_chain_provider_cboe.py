"""CBOE delayed chain: third fallback after Polygon and yfinance.

Nov 2 2026 failure: Polygon rows were all skipped for mid 0 on the
Massive Starter plan, and yfinance returned no option expiries on
Render, leaving lookups with no chain and no Options Strategies.
CBOE delayed quotes return real bid/ask, so they are the third
source, tried only after both live sources fail, and labelled
cboe_delayed all the way to the UI. A last trade is never used as
a premium, and Greeks are never invented: IV 0 rows report gamma,
vega, and theta as None.
"""
import os
import sys
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.chain_provider import ChainProvider, _parse_cboe_symbol
from services.option_strategies import build_option_strategies


def _symbol(kind, strike, expiry_date):
    letter = "C" if kind == "call" else "P"
    return f"TSLA{expiry_date.strftime('%y%m%d')}{letter}{int(strike * 1000):08d}"


def _expiry_in_window(days=20):
    return date.today() + timedelta(days=days)


def _cboe_options(expiry_date):
    return [
        {
            "option": _symbol("call", 405.0, expiry_date),
            "bid": 18.30, "ask": 18.45, "iv": 0.4637,
            "open_interest": 4627, "volume": 2407,
            "delta": 0.5513, "gamma": 0.0093, "vega": 0.359,
            "theta": -0.4617, "last_trade_price": 12.92,
        },
        {
            "option": _symbol("put", 405.0, expiry_date),
            "bid": 12.10, "ask": 12.40, "iv": 0.4500,
            "open_interest": 3100, "volume": 1800,
            "delta": -0.4487, "gamma": 0.0093, "vega": 0.359,
            "theta": -0.4200, "last_trade_price": 12.20,
        },
        {
            # Bid 0, ask 0.01, last trade 5.00: the last trade must
            # never become the premium. Sale price is 0, buy price
            # is the ask.
            "option": _symbol("put", 300.0, expiry_date),
            "bid": 0.0, "ask": 0.01, "iv": 0.5000,
            "open_interest": 1704, "volume": 25,
            "delta": -0.0001, "gamma": 0.0, "vega": 0.0,
            "theta": -0.0006, "last_trade_price": 5.00,
        },
        {
            # IV 0: Greeks are unreliable, so they read None, not 0.0.
            "option": _symbol("call", 250.0, expiry_date),
            "bid": 156.75, "ask": 158.15, "iv": 0.0,
            "open_interest": 21, "volume": 19,
            "delta": 1.0, "gamma": 0.0, "vega": 0.0,
            "theta": 0.0, "last_trade_price": 158.69,
        },
        {"option": "NOT_AN_OPTION", "bid": 1.0, "ask": 1.1},
    ]


def test_parse_cboe_symbol_call_put_and_bad():
    assert _parse_cboe_symbol("TSLA261120C00405000") == ("2026-11-20", "call", 405.0)
    assert _parse_cboe_symbol("TSLA261120P00405000") == ("2026-11-20", "put", 405.0)
    assert _parse_cboe_symbol("NOT_AN_OPTION") is None
    assert _parse_cboe_symbol("") is None


def test_cboe_rows_normalize_bid_ask_greeks_and_never_last_trade():
    provider = ChainProvider()
    expiry_date = _expiry_in_window()
    payload = _cboe_options(expiry_date)
    with mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=payload):
        calls, price, source = provider._fetch_cboe_rows(
            "TSLA", "call", 14, 28, live_price=407.0
        )
        puts, _, _ = provider._fetch_cboe_rows(
            "TSLA", "put", 14, 28, live_price=407.0
        )
    assert source == "cboe_delayed"
    assert price == 407.0
    call_405 = [r for r in calls if r["strike"] == 405.0][0]
    assert call_405["bid"] == 18.30
    assert call_405["ask"] == 18.45
    assert call_405["mid"] == 18.38
    assert call_405["sale_price"] == 18.30
    assert call_405["price_source"] == "bid"
    assert call_405["iv_pct"] == 46.4
    assert call_405["delta"] == 0.5513
    assert call_405["gamma"] == 0.0093
    assert call_405["vega"] == 0.359
    assert call_405["theta_seller"] == 0.4617
    assert call_405["open_interest"] == 4627
    put_300 = [r for r in puts if r["strike"] == 300.0][0]
    assert put_300["sale_price"] == 0.0
    assert put_300["last_trade"] == 5.00
    assert put_300["mid"] == 0.01
    call_250 = [r for r in calls if r["strike"] == 250.0][0]
    assert call_250["gamma"] is None
    assert call_250["vega"] is None
    assert call_250["theta_seller"] is None


def test_fetch_tries_cboe_only_after_polygon_and_yfinance_fail():
    provider = ChainProvider()
    expiry_date = _expiry_in_window()
    payload = _cboe_options(expiry_date)
    with mock.patch.object(ChainProvider, "fetch_price", return_value=407.0), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=([], None, "")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=payload):
        result = provider.fetch("TSLA", "call", 14, 28, near_price=407.0)
    assert hasattr(result, "rows")
    assert result.source == "cboe_delayed"
    assert result.rows
    assert all(r["expiry"] == expiry_date.isoformat() for r in result.rows)


def test_fetch_reports_all_three_sources_when_all_fail():
    provider = ChainProvider()
    with mock.patch.object(ChainProvider, "fetch_price", return_value=407.0), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=([], None, "")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=[]):
        result = provider.fetch("TSLA", "call", 14, 28, near_price=407.0)
    assert not hasattr(result, "rows")
    assert result.sources_tried == ["polygon", "yfinance", "cboe"]
    assert "cboe" in result.reason


def test_fetch_falls_through_to_cboe_when_yfinance_has_no_executable_bid():
    # Nov 18 2026: Yahoo returned rows for MSFT/TSLA/NVDA with every
    # bid at 0.0, and fetch returned them as a live chain, so the
    # picks tab showed three empty tiers while reporting success.
    # A bid-0 chain is not a live quote: fetch must try CBOE next.
    provider = ChainProvider()
    expiry_date = _expiry_in_window()
    payload = _cboe_options(expiry_date)
    yf_rows = [
        {"strike": 405.0, "bid": 0.0, "ask": 0.0, "delta": 0.55},
        {"strike": 410.0, "bid": 0.0, "ask": 0.0, "delta": 0.50},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=407.0), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 407.0, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=payload):
        result = provider.fetch("TSLA", "call", 14, 28, near_price=407.0)
    assert hasattr(result, "rows")
    assert result.source == "cboe_delayed"
    assert any(r["bid"] > 0 for r in result.rows)


def test_fetch_falls_through_to_cboe_when_yfinance_only_bid_is_far_from_price():
    # AAPL Dec 18 2026: Yahoo's only positive bid was the $35 strike
    # on a $351.91 stock. That stale deep in-the-money quote must not
    # block the CBOE fallback the way a real near-money bid would.
    provider = ChainProvider()
    expiry_date = _expiry_in_window()
    payload = _cboe_options(expiry_date)
    yf_rows = [
        {"strike": 35.0, "bid": 284.80, "ask": 285.00, "delta": 1.0},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=351.91), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 351.91, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=payload):
        result = provider.fetch("AAPL", "call", 14, 28, near_price=351.91)
    assert hasattr(result, "rows")
    assert result.source == "cboe_delayed"
    assert any(r["bid"] > 0 for r in result.rows)


def test_fetch_keeps_yfinance_when_it_has_a_near_money_bid():
    # The price-aware gate must not send a healthy live chain to CBOE.
    provider = ChainProvider()
    yf_rows = [
        {"strike": 405.0, "bid": 18.00, "ask": 18.20, "delta": 0.55},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=407.0), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 407.0, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=[]):
        result = provider.fetch("TSLA", "call", 14, 28, near_price=407.0)
    assert hasattr(result, "rows")
    assert result.source == "yfinance_last_trade"
    assert result.rows == yf_rows


def test_fetch_returns_yfinance_rows_when_cboe_also_has_no_bid():
    # When CBOE has nothing either, the yfinance rows come back so
    # callers can report no_executable_bid instead of the contract
    # vanishing silently.
    provider = ChainProvider()
    yf_rows = [
        {"strike": 405.0, "bid": 0.0, "ask": 0.0, "delta": 0.55},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=407.0), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 407.0, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=[]):
        result = provider.fetch("TSLA", "call", 14, 28, near_price=407.0)
    assert hasattr(result, "rows")
    assert result.source == "yfinance_last_trade"
    assert result.rows == yf_rows


def test_strategies_from_cboe_rows_carry_delayed_source():
    provider = ChainProvider()
    expiry_date = _expiry_in_window()
    payload = _cboe_options(expiry_date)
    with mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=payload):
        calls, _, _ = provider._fetch_cboe_rows(
            "TSLA", "call", 14, 28, live_price=407.0
        )
        puts, _, _ = provider._fetch_cboe_rows(
            "TSLA", "put", 14, 28, live_price=407.0
        )
    result = build_option_strategies(407.0, puts, calls, chain_source="cboe_delayed")
    assert result["available"] is True
    assert result["chain_source"] == "cboe_delayed"
    assert result["best_call"]["status"] == "ok"
    assert result["best_put"]["status"] == "ok"


def test_strategies_unavailable_still_carry_a_reason():
    result = build_option_strategies(407.0, [], [], chain_error="no_listed_chain: test")
    assert result["available"] is False
    assert result["reason"]
