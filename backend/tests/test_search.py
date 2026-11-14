"""Tests for company-name search (services/search.py).

The search turns a company name into matching tickers via Yahoo
search, no API key. A source failure returns an empty list, never
an exception. The Yahoo call is stubbed; no network is used.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.search import clear_search_cache, search_companies


def _quotes():
    return [
        {"symbol": "NVDA", "shortname": "NVIDIA Corporation",
         "longname": "NVIDIA Corporation", "quoteType": "EQUITY",
         "exchDisp": "NASDAQ"},
        {"symbol": "NVDX", "shortname": "T-Rex 2X Long NVIDIA Daily Target ETF",
         "quoteType": "ETF", "exchDisp": "BATS Trading"},
        {"symbol": "SNVDA=F", "shortname": "NVIDIA Futures",
         "quoteType": "FUTURE", "exchDisp": "Chicago Mercantile Exchange"},
        {"symbol": "NVDA.TO", "shortname": "NVIDIA Corporation",
         "quoteType": "EQUITY", "exchDisp": "Toronto"},
        {"symbol": "YOU", "shortname": "Clear Secure, Inc.",
         "longname": "Clear Secure, Inc.", "quoteType": "EQUITY",
         "exchDisp": "NYSE"},
    ]


def _search_ok(query):
    return _quotes()


def _search_fails(query):
    return None


def test_returns_equity_matches_for_a_company_name():
    clear_search_cache()
    results = search_companies("Nvidia", _search=_search_ok)
    tickers = [r["ticker"] for r in results]
    assert "NVDA" in tickers
    assert "NVDA.TO" in tickers
    assert "YOU" in tickers
    assert "NVDX" not in tickers
    assert "SNVDA=F" not in tickers
    first = results[0]
    assert first["ticker"] == "NVDA"
    assert first["name"] == "NVIDIA Corporation"
    assert first["exchange"] == "NASDAQ"


def test_source_failure_returns_empty_list():
    clear_search_cache()
    assert search_companies("Nvidia", _search=_search_fails) == []


def test_query_shorter_than_two_characters_returns_empty_list():
    clear_search_cache()
    assert search_companies("N", _search=_search_ok) == []
    assert search_companies("", _search=_search_ok) == []
    assert search_companies("  ", _search=_search_ok) == []


def test_filters_to_equities_only_when_type_is_present():
    clear_search_cache()
    results = search_companies("Nvidia", _search=_search_ok)
    assert all(r["ticker"] not in ("NVDX", "SNVDA=F") for r in results)


def test_no_type_field_returns_matches_as_is():
    clear_search_cache()
    def _search_no_type(query):
        return [
            {"symbol": "AAA", "shortname": "AAA Corp", "exchDisp": "NYSE"},
            {"symbol": "BBB", "shortname": "BBB Corp", "exchDisp": "NASDAQ"},
        ]
    results = search_companies("AAA", _search=_search_no_type)
    assert [r["ticker"] for r in results] == ["AAA", "BBB"]


def test_limits_to_eight_results():
    clear_search_cache()
    def _search_many(query):
        return [
            {"symbol": f"T{i:02d}", "shortname": f"Company {i}",
             "quoteType": "EQUITY", "exchDisp": "NASDAQ"}
            for i in range(15)
        ]
    results = search_companies("Company", _search=_search_many)
    assert len(results) == 8


def test_results_are_cached_per_query():
    clear_search_cache()
    calls = []
    def _search_counting(query):
        calls.append(query)
        return _quotes()
    search_companies("Nvidia", _search=_search_counting)
    search_companies("Nvidia", _search=_search_counting)
    assert len(calls) == 1


def test_no_em_dash_in_search_strings():
    src = Path(__file__).resolve().parents[1] / "services" / "search.py"
    assert "\u2014" not in src.read_text()
