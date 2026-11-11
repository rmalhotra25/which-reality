"""Tests for bounded in-memory caches (services/cache_utils.py).

Nov 10 2026: the Render service OOM'd and restarted (512 MB free
plan) because every in-memory cache grew one entry per key until
the process restarted. bounded_put drops expired entries first,
then the oldest, so no cache can grow without bound.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.cache_utils import bounded_put


def test_bounded_put_drops_expired_first():
    cache = {"a": (100.0, "old"), "b": (199.0, "fresh")}
    bounded_put(cache, "c", "new", now=200.0, ttl_seconds=60,
                max_entries=10)
    assert "a" not in cache  # 100s old, past the 60s TTL
    assert "b" in cache and "c" in cache


def test_bounded_put_drops_oldest_when_full():
    cache = {f"k{i}": (float(i), i) for i in range(5)}
    bounded_put(cache, "new", 99, now=100.0, ttl_seconds=3600,
                max_entries=5)
    assert len(cache) == 5
    assert "k0" not in cache
    assert "new" in cache
    assert "k4" in cache


def test_bounded_put_refresh_does_not_evict():
    cache = {f"k{i}": (float(i), i) for i in range(5)}
    bounded_put(cache, "k4", 99, now=100.0, ttl_seconds=3600,
                max_entries=5)
    assert len(cache) == 5
    assert cache["k4"] == (100.0, 99)
    assert "k0" in cache


def test_trigger_cache_put_bounded():
    import services.trigger_service as ts

    ts._ANALYSIS_CACHE.clear()
    for i in range(250):
        ts._analysis_cache_put(f"T{i:03d}", {"n": i})
    assert len(ts._ANALYSIS_CACHE) <= ts._ANALYSIS_CACHE_MAX_ENTRIES
    assert "T249" in ts._ANALYSIS_CACHE


def test_cboe_cache_put_bounded():
    import services.chain_provider as cp

    cp._CBOE_CACHE.clear()
    for i in range(60):
        cp._cboe_cache_put(f"T{i:03d}", [{"strike": 100.0}])
    assert len(cp._CBOE_CACHE) <= cp._CBOE_CACHE_MAX_ENTRIES
    assert "T059" in cp._CBOE_CACHE


def test_screener_cache_put_bounded():
    import services.fmp_client as fmp

    fmp._SCREENER_CACHE.clear()
    for i in range(30):
        fmp._screener_cache_put(f"key{i}", {"status": "ok"})
    assert len(fmp._SCREENER_CACHE) <= fmp._SCREENER_CACHE_MAX_ENTRIES
    assert "key29" in fmp._SCREENER_CACHE


def test_lookup_cache_bounded(monkeypatch):
    import services.ticker_lookup as tl

    tl.clear_lookup_cache()
    monkeypatch.setattr(
        tl, "evaluate_lookup",
        lambda ticker, db=None, signal_date=None: {
            "ticker": ticker, "verdict": "WAIT"})
    for i in range(150):
        tl.lookup_ticker(f"T{i:03d}")
    assert len(tl._CACHE) <= tl._LOOKUP_CACHE_MAX_ENTRIES
    assert "T149" in tl._CACHE
