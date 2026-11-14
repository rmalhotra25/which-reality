"""Tests for the seven bug-hunt fixes (Nov 13, 2026).

1. Tri-state trend: unknown price or MA yields None for above_ma50
   and above_ma200, and the verdict never says "below its 200-day
   average" when the data is unknown.
3. Top 5 lock: concurrent cold loads share one computation.
4. SPY gate yfinance fallback: Finnhub and Polygon fail, yfinance
   succeeds, the gate resolves.
7. Unknown API paths return 404 JSON, not the SPA HTML with a 200.

No network is used; fetchers and the yfinance client are stubbed.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ticker_lookup import _trend, build_verdict


# --- bug 1: tri-state trend -----------------------------------------------

def _unknown_trend():
    return _trend({"price": None, "ma50": None, "ma200": None,
                   "ma50_lag20": None, "ma200_lag20": None, "ma20": None})


def test_trend_unknown_is_none_not_false():
    trend = _unknown_trend()
    assert trend["above_ma50"] is None
    assert trend["above_ma200"] is None
    assert trend["price"] is None


def test_trend_known_still_bool():
    trend = _trend({"price": 200.0, "ma50": 190.0, "ma200": 180.0,
                    "ma50_lag20": 185.0, "ma200_lag20": 175.0, "ma20": 195.0})
    assert trend["above_ma50"] is True
    assert trend["above_ma200"] is True
    trend = _trend({"price": 170.0, "ma50": 190.0, "ma200": 180.0,
                    "ma50_lag20": 185.0, "ma200_lag20": 175.0, "ma20": 175.0})
    assert trend["above_ma50"] is False
    assert trend["above_ma200"] is False


def _fail_setups():
    return [
        {"setup_key": "quality_pullback", "setup_name": "Quality Pullback",
         "rule_result": "fail", "status": "SHADOW", "conditions": {},
         "action": None, "suppressed_reason": None},
        {"setup_key": "volume_breakout", "setup_name": "Volume Breakout",
         "rule_result": "fail", "status": "SHADOW", "conditions": {},
         "action": None, "suppressed_reason": None},
    ]


def test_verdict_unknown_trend_says_cannot_judge_not_below():
    verdict = build_verdict(
        "TEST", price=None, setups=_fail_setups(),
        earnings={"status": "known", "earnings_days": 18,
                  "earnings_date": "2026-11-17"},
        spy_gate={"spy_above_200": True, "spy_vs_200ma_pct": 5.6, "gate": "pass"},
        quality={"composite": 80.0, "grade": "A",
                 "components": {"trend": 80.0, "rsi": 80.0, "volume": 80.0},
                 "inputs": {"rsi": 60.0, "volume_ratio_vs_20d": 1.0,
                            "iv_percentile": None},
                 "note": "Display only."},
        trend=_unknown_trend(), iv_percentile=None,
        news={"status": "fresh_news", "source": "polygon_news", "error": None,
              "latest": None, "fresh_company_release": False,
              "note": "No fresh company news."},
        chain_puts=[], chain_calls=[],
        indicators={"prev_close": None, "prior_high_55": None},
    )
    stock = verdict["stock"]
    assert stock["tier"] == "cannot_judge"
    joined = " ".join(stock["reasons"])
    assert "below its 200-day average" not in joined
    assert "below its 50-day average" not in joined
    assert "trend averages are unavailable" in joined


# --- bug 3: top stocks lock -----------------------------------------------

def test_concurrent_cold_loads_share_one_computation():
    from services import top_stocks as ts

    calls = []
    lock = threading.Lock()

    def counting_fetcher(ticker):
        with lock:
            calls.append(ticker)
        time.sleep(0.05)
        return None

    ts.clear_top_stocks_cache()
    results = []
    errors = []

    def run():
        try:
            results.append(ts.build_top_stocks(fetcher=counting_fetcher))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert len(results) == 3
    assert all(r["status"] == "ok" for r in results)
    # One build grades the 20-ticker universe once; without the lock
    # three concurrent cold loads would grade it three times.
    assert len(calls) == 20
    ts.clear_top_stocks_cache()


# --- bug 4: SPY yfinance fallback ------------------------------------------

def _stub_feed_modules(monkeypatch, finnhub_fn, polygon_fn):
    """Stub the Finnhub and Polygon client modules in sys.modules.

    The real finnhub package is not installed in the sandbox, so
    patching the attribute would fail at import; stubbing the
    module is the same seam the code under test uses.
    """
    import types
    finnhub_stub = types.ModuleType("services.finnhub_client")
    finnhub_stub.get_candles = finnhub_fn
    monkeypatch.setitem(sys.modules, "services.finnhub_client", finnhub_stub)
    polygon_stub = types.ModuleType("services.polygon_client")
    polygon_stub.get_dated_closes = polygon_fn
    monkeypatch.setitem(sys.modules, "services.polygon_client", polygon_stub)


def test_spy_falls_back_to_yfinance(monkeypatch):
    import pandas as pd
    import services.market_context as mc

    def _fail(*args, **kwargs):
        raise RuntimeError("feed down")

    _stub_feed_modules(monkeypatch, _fail, _fail)

    closes = [100.0 + i * 0.1 for i in range(250)]
    idx = pd.date_range("2025-11-01", periods=250, freq="B")

    class _StubTicker:
        def __init__(self, symbol):
            assert symbol == "SPY"

        def history(self, period="300d"):
            return pd.DataFrame({"Close": closes}, index=idx)

    monkeypatch.setattr("yfinance.Ticker", _StubTicker)
    price, ma50, ma200, as_of = mc._fetch_spy()
    assert price == closes[-1]
    assert ma50 is not None and abs(ma50 - sum(closes[-50:]) / 50) < 1e-9
    assert ma200 is not None and abs(ma200 - sum(closes[-200:]) / 200) < 1e-9
    assert as_of == idx[-1].date()


def test_spy_all_feeds_down_returns_nones(monkeypatch):
    import services.market_context as mc

    def _fail(*args, **kwargs):
        raise RuntimeError("feed down")

    _stub_feed_modules(monkeypatch, _fail, _fail)

    class _StubTicker:
        def __init__(self, symbol):
            pass

        def history(self, period="300d"):
            raise RuntimeError("yfinance down")

    monkeypatch.setattr("yfinance.Ticker", _StubTicker)
    assert mc._fetch_spy() == (None, None, None, None)


# --- bug 7: unknown API paths return 404 JSON -------------------------------

def test_api_paths_without_ticker_return_404_json():
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    for path in ["/api/lookup/", "/api/recommendation/", "/api/story/"]:
        res = client.get(path)
        assert res.status_code == 404, path
        assert "text/html" not in res.headers.get("content-type", ""), path
        assert res.json().get("detail") == "Not found", path


def test_spa_still_serves_frontend():
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.get("/some-frontend-route")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


# --- no em dash in the diff -----------------------------------------------
# main.py and StorySection.jsx carry pre-existing em dashes outside
# this change, so the check is on added lines only, which is what
# the standing rule covers.

def test_no_em_dash_in_added_lines():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        ["git", "diff", "--unified=0"], cwd=root,
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            assert "—" not in line, line
