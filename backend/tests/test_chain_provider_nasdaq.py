"""Nasdaq public option chain: delayed source after yfinance.

Nasdaq's public API serves the nearest expiry only, with real
bid/ask where Yahoo shows zeros (ABT Nov 27 2026: Yahoo showed no
bid on any strike; Nasdaq showed the $105 call at $0.60 bid). It
answers datacenter IPs, unlike CBOE's CDN, so it is the delayed
source most likely to work from the deployed app. Quotes are
delayed about 15 minutes and carry no IV or Greeks, so delta and
theta are Black-Scholes on historical vol.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.chain_provider import ChainProvider, _nasdaq_num


def _expiry(days=4):
    return (date.today() + timedelta(days=days)).strftime("%b %d, %Y")


def _nasdaq_payload(expiry_label):
    return {
        "data": {
            "table": {
                "rows": [
                    {
                        "expiryDate": expiry_label,
                        "strike": "105.00",
                        "c_Bid": "0.60", "c_Ask": "1.15", "c_Last": "0.80",
                        "c_Volume": "14", "c_Openinterest": "59",
                        "p_Bid": "2.10", "p_Ask": "2.60", "p_Last": "2.30",
                        "p_Volume": "9", "p_Openinterest": "120",
                    },
                    {
                        "expiryDate": expiry_label,
                        "strike": "110.00",
                        "c_Bid": "--", "c_Ask": "--", "c_Last": "0.10",
                        "c_Volume": "13", "c_Openinterest": "277",
                        "p_Bid": "--", "p_Ask": "--", "p_Last": "5.40",
                        "p_Volume": "2", "p_Openinterest": "88",
                    },
                    {
                        "expiryDate": expiry_label,
                        "strike": "100.00",
                        "c_Bid": "--", "c_Ask": "--", "c_Last": "5.05",
                        "c_Volume": "--", "c_Openinterest": "16",
                        "p_Bid": "0.05", "p_Ask": "0.30", "p_Last": "0.12",
                        "p_Volume": "4", "p_Openinterest": "40",
                    },
                ]
            }
        }
    }


class _FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mock_urlopen(payload):
    return mock.patch(
        "urllib.request.urlopen", return_value=_FakeResponse(payload)
    )


def test_nasdaq_num_parses_dashes_commas_and_none():
    assert _nasdaq_num("--") is None
    assert _nasdaq_num(None) is None
    assert _nasdaq_num("1,234.50") == 1234.50
    assert _nasdaq_num("0.60") == 0.60


def test_nasdaq_rows_parse_nearest_expiry_with_real_bid():
    provider = ChainProvider()
    payload = _nasdaq_payload(_expiry(4))
    with _mock_urlopen(payload), \
         mock.patch("services.chain_provider._historical_volatility", return_value=0.25):
        rows, price, source = provider._fetch_nasdaq_rows(
            "ABT", "call", 1, 7, live_price=102.97
        )
    assert source == "nasdaq_delayed"
    assert price == 102.97
    row_105 = [r for r in rows if r["strike"] == 105.0][0]
    assert row_105["bid"] == 0.60
    assert row_105["ask"] == 1.15
    assert row_105["sale_price"] == 0.60
    assert row_105["price_source"] == "bid"
    assert row_105["open_interest"] == 59
    assert row_105["iv_pct"] == 25.0
    assert 0.15 < row_105["delta"] < 0.6
    row_110 = [r for r in rows if r["strike"] == 110.0][0]
    assert row_110["bid"] == 0.0
    assert row_110["sale_price"] == 0.0
    assert row_110["last_trade"] == 0.10


def test_nasdaq_rows_skipped_when_expiry_outside_window():
    provider = ChainProvider()
    payload = _nasdaq_payload(_expiry(4))
    with _mock_urlopen(payload):
        rows, price, source = provider._fetch_nasdaq_rows(
            "ABT", "call", 14, 28, live_price=102.97
        )
    assert rows == []
    assert source == ""
    assert "outside" in provider.last_nasdaq_note


def test_fetch_tries_nasdaq_after_yfinance_before_cboe():
    provider = ChainProvider()
    payload = _nasdaq_payload(_expiry(4))
    yf_rows = [
        {"strike": 105.0, "bid": 0.0, "ask": 0.0, "delta": 0.40},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=102.97), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 102.97, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=[]), \
         _mock_urlopen(payload), \
         mock.patch("services.chain_provider._historical_volatility", return_value=0.25):
        result = provider.fetch("ABT", "call", 1, 7, near_price=102.97)
    assert hasattr(result, "rows")
    assert result.source == "nasdaq_delayed"
    assert any(r["strike"] == 105.0 and r["bid"] == 0.60 for r in result.rows)
    assert any("nasdaq ok" in n for n in result.notes)


def test_fetch_skips_nasdaq_when_its_expiry_is_outside_window():
    provider = ChainProvider()
    payload = _nasdaq_payload(_expiry(4))
    yf_rows = [
        {"strike": 105.0, "bid": 0.0, "ask": 0.0, "delta": 0.40},
    ]
    with mock.patch.object(ChainProvider, "fetch_price", return_value=102.97), \
         mock.patch.object(ChainProvider, "_fetch_polygon_rows", return_value=([], None)), \
         mock.patch.object(ChainProvider, "_fetch_yfinance_rows", return_value=(yf_rows, 102.97, "yfinance_last_trade")), \
         mock.patch.object(ChainProvider, "_fetch_cboe_payload", return_value=[]), \
         _mock_urlopen(payload):
        result = provider.fetch("ABT", "call", 14, 28, near_price=102.97)
    assert hasattr(result, "rows")
    assert result.source == "yfinance_last_trade"
    assert result.rows == yf_rows
