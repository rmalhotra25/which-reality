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

def _stub_build(monkeypatch, **overrides):
    import services.story as story

    clear_story_cache()
    monkeypatch.setattr(story, "_fetch_price",
                        lambda t: (169.14, "2026-11-10", None))
    monkeypatch.setattr(story, "_fetch_yinfo", lambda t: {
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
    })
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
    assert payload["targets"]["analysts"]["buy"] == 22
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
