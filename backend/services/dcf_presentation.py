"""Plain-language presentation for a lookup DCF. Presentation only.

This module changes no DCF math, no verdict rule, and no gating.
It takes the DCF already computed by build_longterm and turns it
into the few lines the simple view shows: base fair value plus
the bear-to-bull range, the inputs that drive it, a framing
sentence that says a DCF is not a price target, and a
reliability warning when the DCF cannot anchor a price.

Reliability guardrail, stated plainly:
- Reverse DCF implied growth above 25% means the market is
  pricing in growth far beyond the cash flows in the model.
- Terminal methods disagreeing by more than 25% (the existing
  wide_disagreement flag) means two reasonable terminal values
  give very different answers.
Either one makes the DCF unreliable as a price anchor. The DCF
is still shown, labelled, never hidden, because hiding it would
hide the overvaluation signal. It is never presented as an
intrinsic value in that case.
"""


def build_dcf_presentation(dcf, price, wacc=None, verdict=None):
    """Return the simple-view presentation for one DCF, or None.

    dcf is the build_longterm dcf dict (fair_value, upside_pct,
    revenue_millions, fcf_millions, fcf_margin_pct,
    revenue_growth_pct, reverse_dcf_implied_growth_pct,
    exit_multiple_check). price is today's price. wacc is the
    build_longterm wacc dict, or None. verdict is the long-term
    verdict string, used only to word the warning for an
    overvalued name; it never changes the numbers.
    """
    if not dcf:
        return None
    fair = dcf.get("fair_value") or {}
    bear = fair.get("bear")
    base = fair.get("base")
    bull = fair.get("bull")
    if bear is None or base is None or bull is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    implied = dcf.get("reverse_dcf_implied_growth_pct")
    exit_check = dcf.get("exit_multiple_check") or {}
    wide = bool(exit_check.get("wide_disagreement"))
    high_implied = implied is not None and float(implied) > 25.0
    unreliable = bool(high_implied or wide)
    framing = (
        f"On today's cash flows, this DCF says ${base}, "
        f"market is ${price}, so the market is paying for growth "
        f"not yet in cash flows. This is not a price target."
        if price is not None
        else (
            f"On today's cash flows, this DCF says ${base}. "
            f"This is not a price target."
        )
    )
    warning = None
    if unreliable:
        warning = (
            "DCF is not a reliable price anchor for this name. "
            f"Do not treat ${base} as an intrinsic value."
        )
        if verdict == "weak":
            warning += (
                " Treat it as overvalued on current cash flows, "
                f"not as an ${base} intrinsic value."
            )
    wacc_pct = None
    if wacc:
        wacc_pct = wacc.get("wacc_pct")
    return {
        "bear": bear,
        "base": base,
        "bull": bull,
        "range_label": f"${bear} to ${bull}",
        "framing": framing,
        "unreliable": unreliable,
        "high_implied_growth": high_implied,
        "wide_terminal_disagreement": wide,
        "implied_growth_pct": implied,
        "warning": warning,
        "inputs_line": (
            f"Revenue ${dcf.get('revenue_millions')}M, "
            f"FCF ${dcf.get('fcf_millions')}M "
            f"({dcf.get('fcf_margin_pct')}% margin), "
            f"revenue growth {dcf.get('revenue_growth_pct')}%, "
            f"WACC {wacc_pct}%."
        ),
        "exit_multiple_fair_value": exit_check.get("fair_value"),
        "gordon_fair_value": exit_check.get("gordon_fair_value"),
        "disagreement_pct": exit_check.get("disagreement_pct"),
    }
