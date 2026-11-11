"""Tests for the Company Story view (services/story.py).

The Story is a read-only explainer: quant decides the grade, gauges,
tailwinds and headwinds from rules. These tests pin those rules, the
missing-data behavior, and the payload shape. Live fetching is stubbed
in the builder tests; no network is used.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.story import (
    _cagr,
    _segments_from_rows,
    build_story,
    build_tailwinds_headwinds,
    clear_story_cache,
    grade_gauges,
    story_line,
    what_would_change,
)


def _pltr_segments():
    return {
        "product": [
            {"name": "Government", "revenue": 2.4e9, "pct": 54.0, "growth_pct": 53.0},
            {"name": "Commercial", "revenue": 2.0e9, "pct": 46.0, "growth_pct": 60.0},
        ],
        "region": [
            {"name": "United States", "revenue": 3.3e9, "pct": 75.0, "growth_pct": 75.0},
            {"name": "United Kingdom", "revenue": 0.4e9, "pct": 9.0, "growth_pct": 20.0},
            {"name": "Rest of World", "revenue": 0.7e9, "pct": 16.0, "growth_pct": 10.0},
        ],
        "as_of": "FY2025",
        "source": "fmp",
    }


# --- grade and gauges -------------------------------------------------------

def test_pltr_like_inputs_grade_b_valuation_is_the_drag():
    # PLTR Nov 10 2026: CAGR ~33%, gross 84.7%, operating 46.9%,
    # net cash (D/E ~0.1), forward P/E 66.5 vs peer median ~42.
    # The honest grade is B, not the reference screenshot's A,
    # because 66x earnings is Expensive, not Cheap.
    out = grade_gauges(0.329, 0.847, 0.469, 66.5, 42.0, net_cash=10.3e9)
    assert out["grade"] == "B"
    assert out["gauges"]["growth"]["label"] == "Strong"
    assert out["gauges"]["margins"]["label"] == "Strong"
    assert out["gauges"]["debt"]["label"] == "Low"
    assert "net cash $10.3B" in out["gauges"]["debt"]["basis"]
    assert out["gauges"]["price"]["label"] == "Expensive"
    assert "vs peer median 42.0" in out["gauges"]["price"]["basis"]
    assert "Valuation Expensive is the drag" in out["grade_reason"]


def test_grade_a_when_all_four_favorable():
    out = grade_gauges(0.25, 0.75, 0.30, 20.0, 30.0, net_cash=5.0e9)
    assert out["grade"] == "A"
    assert out["gauges"]["price"]["label"] == "Cheap"


def test_grade_f_when_nothing_favorable():
    out = grade_gauges(0.05, 0.40, 0.10, 90.0, 30.0, net_cash=-5.0e9, total_debt=5.0e9, free_cashflow=1.0e9)
    assert out["grade"] == "F"


def test_unknown_gauge_does_not_count_and_is_named():
    out = grade_gauges(0.25, 0.75, 0.30, 20.0, None)
    assert out["gauges"]["debt"]["label"] == "Unknown"
    assert out["gauges"]["price"]["label"] == "Unknown"
    assert out["grade"] == "C"  # Growth + Margins favorable only
    assert "Debt" in out["grade_reason"] and "Valuation" in out["grade_reason"]


def test_price_gauge_boundaries():
    assert grade_gauges(0.25, 0.75, 0.30, 23.0, 30.0, net_cash=5.0e9)["gauges"]["price"]["label"] == "Cheap"
    assert grade_gauges(0.25, 0.75, 0.30, 30.0, 30.0, net_cash=5.0e9)["gauges"]["price"]["label"] == "Fair"
    assert grade_gauges(0.25, 0.75, 0.30, 45.0, 30.0, net_cash=5.0e9)["gauges"]["price"]["label"] == "Fair"
    assert grade_gauges(0.25, 0.75, 0.30, 46.0, 30.0, net_cash=5.0e9)["gauges"]["price"]["label"] == "Expensive"


def test_debt_gauge_uses_net_cash_not_yahoo_debt_to_equity():
    # PLTR Nov 10 2026: Yahoo's debtToEquity reads 1.99, but the
    # company holds $10.6B of cash against $0.2B of debt. Net cash
    # wins; the misleading field must not flip the gauge to High.
    out = grade_gauges(0.329, 0.847, 0.469, 66.5, 42.0,
                       net_cash=10.3e9, debt_to_equity=1.99)
    assert out["gauges"]["debt"]["label"] == "Low"
    assert out["grade"] == "B"


def test_debt_gauge_net_debt_moderate_when_payable_from_fcf():
    out = grade_gauges(0.25, 0.75, 0.30, 20.0, 30.0,
                       net_cash=-1.0e9, total_debt=1.0e9,
                       free_cashflow=1.0e9)
    assert out["gauges"]["debt"]["label"] == "Moderate"


def test_debt_gauge_falls_back_to_debt_to_equity():
    out = grade_gauges(0.25, 0.75, 0.30, 20.0, 30.0, debt_to_equity=0.2)
    assert out["gauges"]["debt"]["label"] == "Low"
    out = grade_gauges(0.25, 0.75, 0.30, 20.0, 30.0, debt_to_equity=1.5)
    assert out["gauges"]["debt"]["label"] == "High"


def test_cagr():
    assert abs(_cagr(1.906e9, 4.475e9, 3) - 0.329) < 0.005
    assert _cagr(None, 10, 3) is None
    assert _cagr(0, 10, 3) is None


# --- tailwinds and headwinds ------------------------------------------------

def test_pltr_like_tailwinds_and_headwinds():
    tail, head = build_tailwinds_headwinds(
        _pltr_segments(), 0.329, 0.847, 0.469, 66.5)
    titles_t = [t["title"] for t in tail]
    titles_h = [h["title"] for h in head]
    assert "Commercial growth surge" in titles_t
    assert "High profitability" in titles_t
    assert "Strong US demand" in titles_t
    assert "Fast growth" in titles_t
    assert "Rich valuation" in titles_h
    assert "Government dependence" in titles_h
    assert "Weak international growth" in titles_h
    assert all(t["strength"] in (1, 2, 3) for t in tail + head)


def test_no_segments_skips_segment_rules_only():
    tail, head = build_tailwinds_headwinds(
        None, 0.329, 0.847, 0.469, 66.5)
    titles_t = [t["title"] for t in tail]
    titles_h = [h["title"] for h in head]
    assert "High profitability" in titles_t
    assert "Fast growth" in titles_t
    assert "Rich valuation" in titles_h
    assert "Commercial growth surge" not in titles_t
    assert "Government dependence" not in titles_h
    assert "Weak international growth" not in titles_h


# --- story line and what-would-change ---------------------------------------

def test_story_line_templated_from_numbers():
    line = story_line("Palantir Technologies Inc.",
                      "Software - Infrastructure", 0.329, 0.847, 66.5)
    assert "Palantir Technologies Inc." in line
    assert "software infrastructure" in line
    assert "32.9%" in line
    assert "84.7%" in line
    assert "66" in line


def test_what_would_change_names_the_break():
    _, head = build_tailwinds_headwinds(
        _pltr_segments(), 0.329, 0.847, 0.469, 66.5)
    line = what_would_change(head)
    assert line.startswith("What would change this assessment:")
    assert "government contracts" in line or "multiple" in line


def test_what_would_change_without_headwinds():
    assert what_would_change([]) == (
        "What would change this assessment: if revenue growth slows "
        "well below its recent pace.")


# --- segment parsing ---------------------------------------------------------

def test_segments_from_rows_groups_and_grows():
    rows = [
        {"date": "2024-12-31", "segment": "Government", "revenue": 2.0e9},
        {"date": "2024-12-31", "segment": "Commercial", "revenue": 1.5e9},
        {"date": "2023-12-31", "segment": "Government", "revenue": 1.6e9},
        {"date": "2023-12-31", "segment": "Commercial", "revenue": 1.0e9},
    ]
    items, year = _segments_from_rows(rows)
    assert year == "2024"
    gov = [i for i in items if i["name"] == "Government"][0]
    assert gov["pct"] == 57.1
    assert gov["growth_pct"] == 25.0
    assert _segments_from_rows([]) == (None, None)
    assert _segments_from_rows(None) == (None, None)


# --- builder with stubbed fetchers -------------------------------------------

def _pltr_yinfo():
    return {
        "longName": "Palantir Technologies Inc.",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "forwardPE": 66.5, "grossMargins": 0.847,
        "operatingMargins": 0.469, "debtToEquity": 1.99,
        "totalCash": 10.56e9, "totalDebt": 0.225e9,
        "freeCashflow": 1.5e9,
        "trailingEps": 0.63, "fiftyTwoWeekLow": 106.37,
        "fiftyTwoWeekHigh": 212.94,
        "targetMeanPrice": 222.25, "targetLowPrice": 80.0,
        "targetHighPrice": 273.0,
    }


def _yinfo_without(*keys):
    return {k: v for k, v in _pltr_yinfo().items() if k not in keys}


def _stub_build(monkeypatch, **overrides):
    import services.story as story

    clear_story_cache()
    monkeypatch.setattr(story, "_fetch_price",
                        lambda t: (169.14, "2026-11-10", None))
    monkeypatch.setattr(story, "_fetch_yinfo", lambda t: _pltr_yinfo())
    monkeypatch.setattr(story, "_fetch_revenue_history", lambda t: [
        {"year": 2022, "revenue": 1.906e9, "growth_pct": None, "estimated": False},
        {"year": 2023, "revenue": 2.225e9, "growth_pct": 16.7, "estimated": False},
        {"year": 2024, "revenue": 2.866e9, "growth_pct": 28.8, "estimated": False},
        {"year": 2025, "revenue": 4.475e9, "growth_pct": 56.1, "estimated": False},
    ])
    monkeypatch.setattr(story, "_fetch_revenue_estimates", lambda t, y: [
        {"year": 2026, "revenue": 8.55e9, "growth_pct": 91.0, "estimated": True},
        {"year": 2027, "revenue": 13.12e9, "growth_pct": 53.5, "estimated": True},
    ])
    monkeypatch.setattr(story, "_fetch_recommendations", lambda t: {
        "buy": 22, "hold": 9, "sell": 2, "total": 33})
    monkeypatch.setattr(story, "_fetch_peers", lambda t, n: ([
        {"ticker": "MSFT", "name": "MSFT", "share_pct": 64.1,
         "is_subject": False, "forward_pe": 30.0},
        {"ticker": "PLTR", "name": "Palantir Technologies Inc.",
         "share_pct": 6.6, "is_subject": True, "forward_pe": 66.5},
        {"ticker": "ORCL", "name": "ORCL", "share_pct": 5.9,
         "is_subject": False, "forward_pe": 28.0},
        {"ticker": "PANW", "name": "PANW", "share_pct": 4.3,
         "is_subject": False, "forward_pe": 45.0},
        {"ticker": "CRWD", "name": "CRWD", "share_pct": 3.7,
         "is_subject": False, "forward_pe": 55.0},
        {"ticker": "NET", "name": "NET", "share_pct": 1.8,
         "is_subject": False, "forward_pe": 90.0},
        {"ticker": "FTNT", "name": "FTNT", "share_pct": 1.5,
         "is_subject": False, "forward_pe": 28.0},
        {"ticker": "SNPS", "name": "SNPS", "share_pct": 1.4,
         "is_subject": False, "forward_pe": 38.0},
    ], None))
    monkeypatch.setattr(story, "_fetch_segments",
                        lambda t: (_pltr_segments(), None))
    monkeypatch.setattr(story, "_fetch_dcf", lambda t, p: (
        {"base": 120.0, "bear": 80.0, "bull": 200.0, "verdict": "watch"}, None))
    monkeypatch.setattr(story, "_fetch_earnings_date",
                        lambda t: "2026-11-17")
    for key, fn in overrides.items():
        monkeypatch.setattr(story, key, fn)
    return story.build_story("PLTR")


def test_builder_pltr_payload_shape(monkeypatch):
    payload = _stub_build(monkeypatch)
    assert payload["status"] == "ok"
    assert payload["ticker"] == "PLTR"
    assert payload["price"] == 169.14
    assert payload["grade"] == "B"
    assert "Valuation Expensive is the drag" in payload["grade_reason"]
    assert payload["gauges"]["debt"]["label"] == "Low"
    assert "net cash" in payload["gauges"]["debt"]["basis"]
    assert payload["earnings_date"] == "2026-11-17"
    assert payload["week52"]["low"] == 106.37
    assert payload["segments"]["as_of"] == "FY2025"
    bars = payload["growth"]["bars"]
    assert [b["year"] for b in bars] == [2022, 2023, 2024, 2025, 2026, 2027]
    assert bars[-1]["estimated"] is True
    assert payload["growth"]["multiple_text"] == "2.3x revenue in 3 years"
    assert payload["targets"]["mean"] == 222.25
    assert payload["targets"]["dcf_base"] == 120.0
    assert payload["targets"]["source"] == "yahoo"
    assert payload["targets"]["analysts"]["buy"] == 22
    assert payload["dcf"] == {"base": 120.0, "bear": 80.0, "bull": 200.0,
                             "verdict": "watch"}
    assert payload["consistency_note"] is None
    assert payload["what_would_change"].startswith("What would change this assessment:")


def test_builder_unavailable_without_price(monkeypatch):
    import services.story as story

    clear_story_cache()
    monkeypatch.setattr(story, "_fetch_price",
                        lambda t: (None, None, "no price history found"))
    payload = story.build_story("FAKE")
    assert payload["status"] == "unavailable"
    assert "no price history" in payload["reason"]


def test_builder_segments_missing_degrades(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_segments=lambda t: (None, "segment data unavailable from FMP"))
    assert payload["segments"] is None
    assert "segment data unavailable from FMP" in payload["notes"]
    titles_h = [h["title"] for h in payload["headwinds"]]
    assert "Government dependence" not in titles_h
    assert "Rich valuation" in titles_h


# --- fallback sources (live Render case: Yahoo company data empty) -------

def test_builder_polygon_fundamentals_fill_empty_yahoo_info(monkeypatch):
    """Live Render case, Nov 10 2026: yfinance info returns nothing,
    so margins, debt, name, industry and valuation come from Polygon
    SEC filings. The grade is B, the same as the Yahoo-backed grade,
    and the notes name the fallback sources."""
    payload = _stub_build(
        monkeypatch,
        _fetch_yinfo=lambda t: {},
        _fetch_polygon_fundamentals=lambda t: {
            "gross_margin": 0.847, "operating_margin": 0.469,
            "net_cash": 10.3e9, "total_debt": 0.225e9,
            "free_cashflow": 1.5e9, "name": "Palantir Technologies Inc.",
            "market_cap": 407.7e9, "shares_outstanding": 2.4e9,
            "sic_description": "Software - Infrastructure"},
        _fetch_fmp_profile=lambda t: None,
        _fetch_fmp_pe=lambda t: None,
        _polygon_pe=lambda t, shares=None: 66.5,
        _fetch_fmp_targets=lambda t: None,
        _fetch_benzinga_targets=lambda t: None,
        _fetch_week52=lambda t, p: {"low": 106.37, "high": 212.94,
                                    "position_pct": 58.9},
    )
    assert payload["grade"] == "B"
    assert payload["gauges"]["margins"]["label"] == "Strong"
    assert payload["gauges"]["debt"]["label"] == "Low"
    assert payload["name"] == "Palantir Technologies Inc."
    assert payload["industry"] == "Software - Infrastructure"
    assert payload["week52"]["low"] == 106.37
    assert payload["targets"] is None
    assert payload["dcf"]["base"] == 120.0
    assert payload["dcf"]["verdict"] == "watch"
    assert any("Polygon SEC filings" in n for n in payload["notes"])
    assert any("analyst price targets unavailable" in n
               for n in payload["notes"])


def test_builder_fmp_targets_when_yahoo_targets_missing(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_yinfo=lambda t: _yinfo_without(
            "targetMeanPrice", "targetLowPrice", "targetHighPrice"),
        _fetch_fmp_targets=lambda t: {"low": 80.0, "mean": 222.25,
                                      "high": 273.0},
    )
    assert payload["targets"]["mean"] == 222.25
    assert payload["targets"]["source"] == "fmp"
    assert payload["targets"]["analysts"] is None
    assert payload["targets"]["dcf_base"] == 120.0
    assert any("targets from FMP" in n for n in payload["notes"])


def test_builder_benzinga_targets_when_fmp_missing(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_yinfo=lambda t: _yinfo_without(
            "targetMeanPrice", "targetLowPrice", "targetHighPrice"),
        _fetch_fmp_targets=lambda t: None,
        _fetch_benzinga_targets=lambda t: {"low": 200.0, "mean": 225.0,
                                           "high": 260.0, "count": 5},
    )
    assert payload["targets"]["source"] == "benzinga"
    assert payload["targets"]["mean"] == 225.0
    assert payload["targets"]["count"] == 5
    assert any("targets from Polygon Benzinga actions" in n
               for n in payload["notes"])


def test_builder_dcf_visible_without_targets(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_yinfo=lambda t: _yinfo_without(
            "targetMeanPrice", "targetLowPrice", "targetHighPrice"),
        _fetch_fmp_targets=lambda t: None,
        _fetch_benzinga_targets=lambda t: None,
    )
    assert payload["targets"] is None
    assert payload["dcf"] == {"base": 120.0, "bear": 80.0, "bull": 200.0,
                             "verdict": "watch"}
    assert "analyst price targets unavailable" in payload["notes"]


def test_builder_everything_unknown_still_grades(monkeypatch):
    """Worst case: every source empty. The Story still returns a
    letter grade (F) with the unknowns named, never a crash and
    never an invented number."""
    payload = _stub_build(
        monkeypatch,
        _fetch_yinfo=lambda t: {},
        _fetch_polygon_fundamentals=lambda t: {},
        _fetch_fmp_profile=lambda t: None,
        _fetch_fmp_pe=lambda t: None,
        _polygon_pe=lambda t, shares=None: None,
        _fetch_fmp_targets=lambda t: None,
        _fetch_benzinga_targets=lambda t: None,
        _fetch_week52=lambda t, p: None,
        _fetch_peers=lambda t, n: (
            None, "peer list unavailable from FMP and Polygon"),
        _fetch_segments=lambda t: (None, "segment data unavailable from FMP"),
        _fetch_dcf=lambda t, p: (None, "no reported statements, so no DCF"),
        _fetch_revenue_history=lambda t: [],
        _fetch_revenue_estimates=lambda t, y: [],
        _fetch_earnings_date=lambda t: None,
    )
    assert payload["status"] == "ok"
    assert payload["grade"] == "F"
    assert payload["name"] == "PLTR"
    assert payload["dcf"] is None
    assert payload["targets"] is None
    assert payload["gauges"]["margins"]["label"] == "Unknown"
    assert payload["gauges"]["debt"]["label"] == "Unknown"
    assert "Debt" in payload["grade_reason"]
    assert "Valuation" in payload["grade_reason"]


def test_polygon_fundamentals_maps_sec_filing(monkeypatch):
    import services.polygon_client as pc
    import services.story as story

    monkeypatch.setattr(pc, "get_financials", lambda t: {
        "revenue": 4.475e9, "gross_profit": 3.79e9,
        "operating_income": 2.10e9, "net_income": 0.9e9,
        "cash": 10.56e9, "total_debt": 0.225e9,
        "free_cash_flow": 1.5e9})
    monkeypatch.setattr(pc, "get_ticker_details", lambda t: {
        "name": "Palantir Technologies Inc.", "market_cap": 407.7e9,
        "shares_outstanding": 2.4e9,
        "sic_description": "Software - Infrastructure"})
    out = story._fetch_polygon_fundamentals("PLTR")
    assert abs(out["gross_margin"] - 3.79 / 4.475) < 1e-6
    assert abs(out["operating_margin"] - 2.10 / 4.475) < 1e-6
    assert abs(out["net_cash"] - (10.56e9 - 0.225e9)) < 1.0
    assert out["total_debt"] == 0.225e9
    assert out["free_cashflow"] == 1.5e9
    assert out["name"] == "Palantir Technologies Inc."
    assert out["shares_outstanding"] == 2.4e9
    assert out["sic_description"] == "Software - Infrastructure"


def test_fmp_targets_maps_consensus(monkeypatch):
    import services.fmp_client as fmp
    import services.story as story

    monkeypatch.setattr(fmp, "_get",
                        lambda path, params=None, timeout=15: [
                            {"symbol": "PLTR", "targetHigh": 273.0,
                             "targetLow": 80.0, "targetConsensus": 222.25,
                             "targetMedian": 220.0}])
    out = story._fetch_fmp_targets("PLTR")
    assert out == {"low": 80.0, "mean": 222.25, "high": 273.0}


def test_fetch_peers_falls_back_to_polygon_related(monkeypatch):
    import services.fmp_client as fmp
    import services.polygon_client as pc
    import services.story as story

    monkeypatch.setattr(fmp, "_get",
                        lambda path, params=None, timeout=15: None)
    monkeypatch.setattr(pc, "get_related_companies",
                        lambda t: ["MSFT", "ORCL"])
    monkeypatch.setattr(story, "_fetch_peer_facts", lambda tickers: {
        "PLTR": {"market_cap": 400e9, "forward_pe": 66.5},
        "MSFT": {"market_cap": 3000e9, "forward_pe": 30.0},
        "ORCL": {"market_cap": 500e9, "forward_pe": 28.0}})
    rows, note = story._fetch_peers("PLTR", "Palantir")
    assert rows is not None
    assert rows[0]["ticker"] == "MSFT"
    assert "Polygon related companies" in note


def test_fetch_peer_facts_pe_chain(monkeypatch):
    import yfinance as yf
    import services.fmp_client as fmp
    import services.polygon_client as pc
    import services.story as story

    class FakeTicker:
        def __init__(self, sym):
            self._sym = sym

        @property
        def info(self):
            if self._sym == "AAA":
                return {"marketCap": 100e9, "forwardPE": 25.0}
            return {}

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    monkeypatch.setattr(pc, "get_ticker_details", lambda t: {
        "market_cap": {"AAA": 100e9, "BBB": 200e9, "CCC": 50e9}.get(t),
        "shares_outstanding": 1e9, "name": t, "sic_description": None})
    monkeypatch.setattr(fmp, "_get",
                        lambda path, params=None, timeout=15: (
                            [{"priceEarningsRatio": 30.0}]
                            if path.startswith("/ratios/BBB") else None))
    monkeypatch.setattr(story, "_polygon_pe",
                        lambda t, shares=None: 40.0 if t == "CCC" else None)
    out = story._fetch_peer_facts(["AAA", "BBB", "CCC"])
    assert out["AAA"]["forward_pe"] == 25.0  # Yahoo
    assert out["BBB"]["forward_pe"] == 30.0  # FMP ratios
    assert out["CCC"]["forward_pe"] == 40.0  # Polygon-computed
    assert out["BBB"]["market_cap"] == 200e9


def test_nan_price_does_not_500(monkeypatch):
    """Nov 10 2026: the live /api/story/PLTR 500'd after the
    fallback merge. The price feed returned a NaN close, and the
    NaN reached the payload; Starlette's JSON encoder rejects
    non-finite floats (allow_nan=False). The Story now keeps its
    grade with the price-dependent fields null, and the payload
    serializes under the same rule Starlette uses."""
    import json

    payload = _stub_build(
        monkeypatch,
        _fetch_price=lambda t: (float("nan"), None, None))
    assert payload["status"] == "ok"
    assert payload["grade"] == "B"
    assert payload["price"] is None
    assert payload["targets"]["now"] is None
    assert payload["targets"]["mean_vs_now_pct"] is None
    json.dumps(payload, allow_nan=False)


def test_to_float_and_sanitize_reject_nonfinite():
    import services.story as story

    assert story._to_float(float("nan")) is None
    assert story._to_float(float("inf")) is None
    assert story._to_float(42.5) == 42.5
    assert story._sanitize({"a": float("nan"),
                            "b": [1.0, float("inf")],
                            "c": {"d": float("nan")}}) == {
        "a": None, "b": [1.0, None], "c": {"d": None}}


def test_story_cache_bounded():
    """Nov 10 2026: the Story cache grew one entry per ticker until
    the process restarted. It now caps at _CACHE_MAX_ENTRIES."""
    import services.story as story

    story.clear_story_cache()
    for i in range(250):
        story._cache_put(f"T{i:03d}", {"status": "ok"})
    assert len(story._CACHE) <= story._CACHE_MAX_ENTRIES
    assert story._cache_get("T249") is not None


def _news_article(title, days_ago=2, publisher="New York Times"):
    from datetime import datetime, timedelta, timezone

    published = (datetime.now(timezone.utc)
                 - timedelta(days=days_ago)).isoformat()
    return {"title": title, "published_at": published,
            "publisher": publisher, "url": "https://example.com/a"}


def test_news_headwind_flags_investigation(monkeypatch):
    """Nov 10 2026: NVDA's Story read 'none flagged' while the Jensen
    Huang investigation was the biggest thing about the company. The
    quant headwinds come from numbers only, so a governance event is
    invisible to them; recent news now fills that gap."""
    payload = _stub_build(
        monkeypatch,
        _fetch_news=lambda t: ([
            _news_article(
                "Nvidia Stock Plunges on Jensen Huang Investigation",
                days_ago=2),
        ], None))
    titles = [h["title"] for h in payload["headwinds"]]
    assert "Governance investigation" in titles
    item = next(h for h in payload["headwinds"]
                if h["title"] == "Governance investigation")
    assert "Jensen Huang Investigation" in item["detail"]
    assert "New York Times" in item["detail"]
    assert item["source"] == "news"
    assert "the investigation clears the company" in \
        payload["what_would_change"]


def test_news_headwind_adds_to_quant_headwinds(monkeypatch):
    """The news headwind is additive: the PLTR stub already has a
    Rich valuation headwind from its 66.5 forward P/E, and the news
    headwind sits beside it instead of replacing it."""
    payload = _stub_build(
        monkeypatch,
        _fetch_news=lambda t: ([
            _news_article("Palantir CEO resigns after board dispute",
                          days_ago=1),
        ], None))
    titles = [h["title"] for h in payload["headwinds"]]
    assert "Rich valuation" in titles
    assert "Leadership change" in titles


def test_news_headwind_skips_stale(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_news=lambda t: ([
            _news_article("Nvidia Stock Plunges on Jensen Huang "
                          "Investigation", days_ago=40),
        ], None))
    titles = [h["title"] for h in payload["headwinds"]]
    assert "Governance investigation" not in titles


def test_news_headwind_skips_untimestamped(monkeypatch):
    article = _news_article("Nvidia Stock Plunges on Jensen Huang "
                            "Investigation")
    article["published_at"] = None
    payload = _stub_build(
        monkeypatch, _fetch_news=lambda t: ([article], None))
    titles = [h["title"] for h in payload["headwinds"]]
    assert "Governance investigation" not in titles


def test_news_headwind_word_boundaries(monkeypatch):
    """'sues' must not match inside 'issues', and 'sec' must not match
    inside 'sector': word boundaries, not substrings."""
    payload = _stub_build(
        monkeypatch,
        _fetch_news=lambda t: ([
            _news_article("Nvidia issues new chip as sector demand "
                          "rises", days_ago=1),
        ], None))
    titles = [h["title"] for h in payload["headwinds"]]
    assert "Legal action" not in titles


def test_news_headwind_fetch_failure_degrades(monkeypatch):
    payload = _stub_build(
        monkeypatch,
        _fetch_news=lambda t: ([], "company news unavailable"))
    assert payload["status"] == "ok"
    assert payload["grade"] == "B"
    assert "company news unavailable" in payload["notes"]
    assert not [h for h in payload["headwinds"]
                if h.get("source") == "news"]
