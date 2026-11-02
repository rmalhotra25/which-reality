"""Three additional DCF methods for ticker lookup.

The statements anchor stays the verdict driver and is never
fitted to the price. Forward scenarios use fixed multipliers
of the 3-year CAGR and current margin, normalized uses a
multi-year average instead of a single year, and sum of parts
never blends a speculative upside into the operating total.
Missing segment data stays missing, never an invented split.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dcf_methods import (
    build_dcf_methods, build_forward_method, build_normalized_method,
    build_sotp_method, forward_scenarios,
)
from services.longterm_valuation import build_longterm


def _snapshot():
    return {
        "status": "verified", "run_date": "2026-10-26",
        "composite": 59.0, "label": "Compounder",
        "smoothed_rule_of_40": 10.1, "rev_cagr_3y_pct": 5.2,
        "fcf_margin_avg_3y_pct": 4.9, "operating_margin_pct": 3.5,
        "roic_pct": 3.3, "ev_to_ebitda": 150.1, "fcf_yield_pct": 0.2,
    }


def _statements(**extra):
    base = {
        "revenue": 94827.0, "fcf": 6220.0, "shares_outstanding": 3950.0,
        "beta": 1.7374, "sector": "Automobiles",
        "revenue_growth_pct": 5.2, "operating_margin_pct": 3.5,
        "ev_to_ebitda": 150.1,
    }
    base.update(extra)
    return base


def test_forward_scenarios_are_fixed_rules_not_price_fitted():
    scenarios = forward_scenarios(0.052, 0.066)
    assert scenarios["bear"]["g1"] == 0.026
    assert scenarios["base"]["g1"] == 0.065
    assert scenarios["bull"]["g1"] == 0.10
    assert scenarios["base"]["fm"] == 0.0825
    assert scenarios["bull"]["fm"] == 0.099
    assert scenarios["bear"]["fm"] == 0.0594


def test_forward_base_between_bear_and_bull_and_price_independent():
    first = build_forward_method(399.81, 94827.0, 0.066, 0.052, 0.141,
                                 399.81 * 3950.0, 3950.0)
    second = build_forward_method(100.0, 94827.0, 0.066, 0.052, 0.141,
                                  100.0 * 3950.0, 3950.0)
    assert first["status"] == "ok"
    fair = first["fair_value"]
    assert fair["bear"] < fair["base"] < fair["bull"]
    # Fair values come from cash flows and WACC, not from the price.
    assert second["fair_value"] == fair
    assert "1.25 times" in first["assumptions"]


def test_normalized_uses_multi_year_averages_not_single_year():
    history = [
        {"revenue": 12000.0, "fcf": 840.0},
        {"revenue": 11000.0, "fcf": 660.0},
        {"revenue": 10000.0, "fcf": 500.0},
    ]
    method = build_normalized_method(
        100.0, 12000.0, 0.07, 0.10, 0.10, 100.0 * 1000.0, 1000.0,
        history, None, 10.0, "fallback_hardcoded_4.5pct")
    assert method["status"] == "ok"
    assert method["normalized_revenue_millions"] == 11000.0
    # Aggregate margin: 2000 / 33000, not the latest year 7%.
    assert method["normalized_fcf_margin_pct"] == 6.1
    assert method["source"] == "history_3y_average"
    fair = method["fair_value"]
    assert fair["bear"] < fair["base"] < fair["bull"]


def test_normalized_falls_back_to_quality_average_margin():
    method = build_normalized_method(
        100.0, 12000.0, 0.07, 0.10, 0.10, 100.0 * 1000.0, 1000.0,
        None, 4.9, 10.0, "fallback_hardcoded_4.5pct")
    assert method["status"] == "ok"
    assert method["normalized_fcf_margin_pct"] == 4.9
    assert method["normalized_revenue_millions"] == 12000.0
    assert "latest year" in method["note"]


def test_normalized_missing_when_no_history_or_average():
    method = build_normalized_method(
        100.0, 12000.0, 0.07, 0.10, 0.10, 100.0 * 1000.0, 1000.0,
        None, None, 10.0, "fallback_hardcoded_4.5pct")
    assert method["status"] == "missing"
    assert method["fair_value"] is None


def test_sotp_upside_is_never_blended_into_operating_total():
    segments = [
        {"name": "Auto", "revenue": 80000.0, "fcf": 5000.0},
        {"name": "Energy", "revenue": 10000.0, "fcf": 1000.0},
    ]
    method = build_sotp_method(
        100.0, 0.10, 1000.0, 0.10, segments,
        {"per_share": 50.0, "source": "test_supplied", "note": "Test only."})
    assert method["status"] == "ok"
    assert method["combined_total"] is None
    assert method["upside"]["per_share"] == 50.0
    assert method["upside"]["status"] == "supplied"
    fair = method["fair_value"]
    assert fair["bear"] < fair["base"] < fair["bull"]
    assert len(method["segments"]) == 2


def test_sotp_missing_segments_are_not_invented():
    method = build_sotp_method(100.0, 0.10, 1000.0, 0.10, None, None)
    assert method["status"] == "unavailable"
    assert method["segments"] == []
    assert method["fair_value"] is None
    assert method["upside"]["status"] == "missing"
    assert method["combined_total"] is None


def test_build_longterm_carries_all_three_methods():
    lt = build_longterm("TSLA", 399.81, _snapshot(),
                        statements=_statements())
    assert lt["dcf"] is not None
    methods = lt["dcf_methods"]
    assert methods is not None
    assert methods["forward"]["status"] == "ok"
    assert methods["normalized"]["status"] == "ok"
    # No segment source is wired, so sum of parts stays unavailable.
    assert methods["sum_of_parts"]["status"] == "unavailable"
    assert methods["sum_of_parts"]["fair_value"] is None
    # Verdict still comes from the anchor, not from any new method.
    assert lt["verdict"] == "weak"
    assert methods["note"].startswith("Context only")
    # Simple view numbers match details: the methods payload is the
    # same object the frontend reads for both views.
    assert methods["forward"]["fair_value"]["base"] > 0
    assert methods["normalized"]["risk_free_source"] == "fallback_hardcoded_4.5pct"


def test_no_em_dashes_in_new_modules():
    base = os.path.join(os.path.dirname(__file__), "..", "services")
    for name in ("dcf_methods.py", "option_strategies.py"):
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            assert chr(8212) not in fh.read()
