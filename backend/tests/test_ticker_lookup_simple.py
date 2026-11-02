"""Simplified ticker lookup and DCF presentation.

Simple view by default: the answer first, then three collapsed
sections, with details behind toggles and a full expanded view
toggle. Nothing is deleted, only collapsed. A DCF is never
presented as a price target, and when implied growth is above
25% or terminal methods disagree by more than 25%, the DCF is
labelled unreliable as a price anchor, not hidden, and not
presented as an intrinsic value. TSLA is the motivating case:
bear $11.63, base $17.74, bull $25.97 at a $399.81 price, implied
growth 52.2%, exit-multiple $70.48 vs Gordon $17.74, disagreement
297.3%. That reads as overvalued on current cash flows with a
reliability warning, not as "TSLA is an $18 stock".
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dcf_presentation import build_dcf_presentation
from services.longterm_valuation import build_longterm


def _tsla_dcf():
    return {
        "fair_value": {"bear": 11.63, "base": 17.74, "bull": 25.97},
        "upside_pct": {"bear": -97.1, "base": -95.6, "bull": -93.5},
        "current_price": 399.81,
        "revenue_millions": 94827.0,
        "fcf_millions": 6220.0,
        "fcf_margin_pct": 6.6,
        "revenue_growth_pct": 5.2,
        "reverse_dcf_implied_growth_pct": 52.2,
        "exit_multiple_check": {
            "method": "industry_exit_multiple_ev_ebitda",
            "multiple": 150.1,
            "fair_value": 70.48,
            "gordon_fair_value": 17.74,
            "disagreement_pct": 297.3,
            "wide_disagreement": True,
        },
    }


def _wacc():
    return {"wacc_pct": 14.1, "risk_free_pct": 4.5,
            "risk_free_source": "fallback_hardcoded_4.5pct"}


def test_tsla_like_dcf_is_unreliable_and_not_a_price_target():
    p = build_dcf_presentation(_tsla_dcf(), 399.81, _wacc(), "weak")
    assert p is not None
    assert p["bear"] == 11.63
    assert p["base"] == 17.74
    assert p["bull"] == 25.97
    assert p["range_label"] == "$11.63 to $25.97"
    assert p["unreliable"] is True
    assert p["high_implied_growth"] is True
    assert p["wide_terminal_disagreement"] is True
    assert "not a price target" in p["framing"].lower()
    assert "not a reliable price anchor" in p["warning"]
    assert "overvalued on current cash flows" in p["warning"]
    assert "not as an $17.74 intrinsic value" in p["warning"]
    assert "94827" in p["inputs_line"]
    assert "6220" in p["inputs_line"]


def test_high_implied_growth_alone_triggers_warning():
    dcf = _tsla_dcf()
    dcf["exit_multiple_check"] = {"wide_disagreement": False,
                                  "fair_value": 18.0,
                                  "gordon_fair_value": 17.74,
                                  "disagreement_pct": 1.5}
    p = build_dcf_presentation(dcf, 399.81, _wacc(), "weak")
    assert p["unreliable"] is True
    assert p["high_implied_growth"] is True
    assert p["wide_terminal_disagreement"] is False


def test_wide_disagreement_alone_triggers_warning():
    dcf = _tsla_dcf()
    dcf["reverse_dcf_implied_growth_pct"] = 10.0
    p = build_dcf_presentation(dcf, 399.81, _wacc(), "weak")
    assert p["unreliable"] is True
    assert p["high_implied_growth"] is False
    assert p["wide_terminal_disagreement"] is True


def test_reliable_dcf_has_no_warning_but_keeps_framing():
    dcf = _tsla_dcf()
    dcf["fair_value"] = {"bear": 300.0, "base": 420.0, "bull": 500.0}
    dcf["reverse_dcf_implied_growth_pct"] = 10.0
    dcf["exit_multiple_check"] = {"wide_disagreement": False,
                                  "fair_value": 410.0,
                                  "gordon_fair_value": 420.0,
                                  "disagreement_pct": -2.4}
    p = build_dcf_presentation(dcf, 399.81, _wacc(), "strong")
    assert p["unreliable"] is False
    assert p["warning"] is None
    assert p["base"] == 420.0
    assert "not a price target" in p["framing"].lower()


def test_no_dcf_returns_no_presentation():
    assert build_dcf_presentation(None, 100.0, _wacc(), "weak") is None
    assert build_dcf_presentation({}, 100.0, _wacc(), "weak") is None


def test_build_longterm_carries_matching_presentation():
    snapshot = {
        "composite": 59.0, "label": "Compounder",
        "smoothed_rule_of_40": 10.1, "rev_cagr_3y_pct": 5.2,
        "fcf_margin_avg_3y_pct": 4.9, "operating_margin_pct": 3.5,
        "roic_pct": 3.3, "ev_to_ebitda": 150.1, "fcf_yield_pct": 0.2,
    }
    statements = {
        "revenue": 94827.0, "fcf": 6220.0, "shares_outstanding": 3950.0,
        "beta": 1.7374, "sector": "Automobiles",
        "revenue_growth_pct": 5.2, "operating_margin_pct": 3.5,
        "ev_to_ebitda": 150.1,
    }
    lt = build_longterm("TSLA", 399.81, snapshot, statements=statements)
    assert lt["dcf"] is not None
    p = lt["dcf_presentation"]
    assert p is not None
    # Simple view numbers must match the details view numbers.
    assert p["bear"] == lt["dcf"]["fair_value"]["bear"]
    assert p["base"] == lt["dcf"]["fair_value"]["base"]
    assert p["bull"] == lt["dcf"]["fair_value"]["bull"]
    assert p["framing"].startswith("On today's cash flows")
    assert "not a price target" in p["framing"].lower()


def _jsx():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "frontend", "src", "tabs", "TickerLookupTab.jsx")
    with open(os.path.normpath(path), encoding="utf-8") as fh:
        return fh.read()


def test_simple_view_is_default_and_sections_are_collapsed():
    src = _jsx()
    assert "ticker_lookup_simple_view" in src
    assert "!== 'full'" in src
    for summary in (
        "Short-term: trend, setup, trigger, invalidation",
        "Long-term: quality, DCF summary, DCA decision",
        "Options: put and call, selected strike only",
    ):
        assert summary in src
    # No details element in the tab opens by default.
    assert not re.search(r"<details[^>]*\bopen\b", src)
    # The full expanded view is one toggle away, persisted.
    assert "Show full expanded view" in src
    assert "Back to simple view" in src


def test_simple_and_details_dcf_share_one_presentation():
    src = _jsx()
    assert "function DcfSummary" in src
    assert "function DcfFraming" in src
    assert "dcfPresentationFor" in src
    # Both components read the same presentation object, so the
    # simple view cannot show a different base value from details.
    assert src.count("dcfPresentationFor(longterm, price)") >= 2


def test_no_em_dashes_in_tab():
    assert chr(8212) not in _jsx()
