import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.covered_call_picks import build_picks, default_expiry, select_tier


def _row(strike, bid, delta, **extra):
    row = {
        "strike": strike, "bid": bid, "ask": round(bid + 0.10, 2),
        "delta": delta, "theta_seller": 0.05, "gamma": 0.01, "vega": 0.10,
        "iv_pct": 40.0, "open_interest": 500, "expiry": "2026-12-04",
    }
    row.update(extra)
    return row


def test_tier_banding_picks_highest_premium_in_each_band():
    # In-the-money strikes are never picks now, so the old $90/$95
    # aggressive rows are out. Aggressive has no out-of-the-money
    # strike in or near its band, middle takes the $100, and the
    # keep-the-premium tier takes the $110.
    rows = [
        _row(90, 12.00, 0.70),
        _row(95, 8.00, 0.60),
        _row(100, 4.00, 0.40),
        _row(105, 2.00, 0.35),
        _row(110, 1.00, 0.20),
        _row(115, 0.50, 0.18),
    ]
    picks, fallbacks, reasons = build_picks(rows, 100.0, 37)
    assert picks["aggressive"] is None
    assert reasons["aggressive"] == "no_band_strike"
    assert picks["middle"]["strike"] == 100
    assert picks["conservative"]["strike"] == 110
    assert fallbacks == []
    assert picks["middle"]["premium_per_contract"] == 400.00
    assert picks["middle"]["premium_yield_pct"] == 4.0
    assert picks["middle"]["breakeven"] == 104.0
    assert picks["middle"]["distance_to_strike_pct"] == 0.0


def test_band_fallback_uses_nearest_strike_and_flags_it():
    rows = [_row(100, 4.00, 0.40), _row(110, 1.00, 0.50)]
    picks, fallbacks, reasons = build_picks(rows, 100.0, 37)
    assert picks["aggressive"]["strike"] == 110
    assert picks["aggressive"]["band_fallback"] is True
    assert "aggressive" in fallbacks
    assert picks["middle"]["strike"] == 100
    assert picks["conservative"] is None
    assert reasons["conservative"] == "no_band_strike"


def test_no_chain_rows_means_no_picks_not_fabricated():
    picks, fallbacks, reasons = build_picks([], 100.0, 37)
    assert picks == {"aggressive": None, "middle": None, "conservative": None}
    assert fallbacks == []
    assert reasons == {
        "aggressive": "no_bid",
        "middle": "no_bid",
        "conservative": "no_bid",
    }


def test_bid_not_last_trade_pricing():
    rows = [_row(100, 2.00, 0.40, last_trade=9.99)]
    picks, _, _ = build_picks(rows, 100.0, 37)
    assert picks["middle"]["bid_per_share"] == 2.00
    assert picks["middle"]["premium_per_contract"] == 200.00


def test_rows_without_bid_or_delta_are_excluded():
    rows = [
        _row(100, 0.0, 0.40),
        _row(105, 2.00, None),
        _row(110, 1.00, 0.20),
    ]
    row, fallback, reason = select_tier(rows, 0.30, 0.45, 0.375)
    assert row["strike"] == 110
    assert fallback is True
    assert reason is None
    # In-band picks come first, so the $110 (delta 0.20) belongs to
    # the conservative tier, not to middle as a fallback. Middle
    # stays empty because its only in-band strike is taken.
    picks, _, reasons = build_picks(rows, 100.0, 37)
    assert picks["aggressive"] is None
    assert reasons["aggressive"] == "no_band_strike"
    assert picks["middle"] is None
    assert reasons["middle"] == "strike_used_by_another_tier"
    assert picks["conservative"]["strike"] == 110
    assert picks["conservative"]["band_fallback"] is False


def test_missing_greeks_stay_missing():
    rows = [_row(100, 4.00, 0.40, gamma=None, vega=None, theta_seller=None)]
    picks, _, _ = build_picks(rows, 100.0, 37)
    assert picks["middle"]["gamma"] is None
    assert picks["middle"]["vega"] is None
    assert picks["middle"]["theta_seller"] is None


def test_default_expiry_prefers_weekly_then_30_to_45_window():
    expiries = [
        {"expiry": "2026-11-20", "dte": 18},
        {"expiry": "2026-12-11", "dte": 39},
        {"expiry": "2026-12-04", "dte": 32},
        {"expiry": "2027-01-15", "dte": 74},
    ]
    assert default_expiry(expiries)["expiry"] == "2026-12-11"
    assert default_expiry([{"expiry": "2026-11-20", "dte": 18}])["dte"] == 18
    assert default_expiry([]) is None
    weekly_first = [
        {"expiry": "2026-11-27", "dte": 4},
        {"expiry": "2026-12-04", "dte": 11},
        {"expiry": "2026-12-18", "dte": 25},
        {"expiry": "2027-01-15", "dte": 53},
    ]
    assert default_expiry(weekly_first)["expiry"] == "2026-11-27"
    assert default_expiry(weekly_first[1:])["expiry"] == "2026-12-04"


def test_annualized_yield_and_shares_total():
    rows = [_row(110, 1.00, 0.20)]
    picks, _, _ = build_picks(rows, 100.0, 37, shares_owned=250)
    assert picks["conservative"]["contracts_covered"] == 2
    assert picks["conservative"]["total_premium_for_shares"] == 200.00
    assert picks["conservative"]["annualized_yield_pct"] == round(1.0 * 365 / 37, 1)


def test_deep_itm_stale_quote_is_rejected():
    # AAPL Dec 18 2026, live: the only row with a positive bid was
    # the $35 strike on a $351.91 stock, bid $284.80, delta 1.0.
    # The strike sits 90% below the price, so no tier may use it.
    rows = [_row(35, 284.80, 1.0)]
    picks, fallbacks, _ = build_picks(rows, 351.91, 30)
    assert picks == {"aggressive": None, "middle": None, "conservative": None}
    assert fallbacks == []


def test_itm_strike_is_never_a_pick_even_with_a_fair_bid():
    # Strike $90 on a $100 stock: intrinsic $10. A $5.00 bid sits
    # $5 below intrinsic, and a $9.50 bid sits $0.50 below it. Both
    # used to be judged on the bid alone; now any in-the-money
    # strike is out, because selling it hands the shares over and
    # most of the "premium" is intrinsic value.
    for bid in (5.00, 9.50):
        rows = [_row(90, bid, 1.0)]
        picks, _, reasons = build_picks(rows, 100.0, 37)
        assert picks == {"aggressive": None, "middle": None, "conservative": None}
        assert reasons["aggressive"] == "no_otm_bid"


def test_abt_dec18_garbage_pick_is_rejected():
    # ABT Dec 18 2026, live Nov 23: the only positive bids were the
    # $82.50 strike (20% in the money, IV 168.2%) and the $170
    # strike (65% out of the money). The old code served the $82.50
    # as all three tiers at a 387% annualized yield. Now: nothing.
    rows = [
        _row(82.50, 27.30, 0.767, iv_pct=168.2, open_interest=17),
        _row(100, 0.0, 0.40),
        _row(105, 0.0, 0.45),
        _row(110, 0.0, 0.30),
        _row(170, 1.27, 0.05, open_interest=46),
    ]
    picks, fallbacks, reasons = build_picks(rows, 102.97, 25)
    assert picks == {"aggressive": None, "middle": None, "conservative": None}
    assert fallbacks == []
    assert reasons["aggressive"] == "no_otm_bid"


def test_min_premium_and_min_open_interest_guards():
    # A $0.10 bid is not worth selling, and a strike with 3
    # contracts of open interest has no real market.
    rows = [_row(105, 0.10, 0.20)]
    picks, _, _ = build_picks(rows, 100.0, 7)
    assert picks["conservative"] is None
    rows = [_row(105, 1.00, 0.20, open_interest=3)]
    picks, _, _ = build_picks(rows, 100.0, 7)
    assert picks["conservative"] is None
    rows = [_row(105, 1.00, 0.20, open_interest=500)]
    picks, _, _ = build_picks(rows, 100.0, 7)
    assert picks["conservative"]["strike"] == 105


def test_iv_cap_rejects_bad_quotes():
    rows = [_row(105, 1.00, 0.20, iv_pct=168.2)]
    picks, _, _ = build_picks(rows, 100.0, 7)
    assert picks["conservative"] is None
    rows = [_row(105, 1.00, 0.20, iv_pct=90.0)]
    picks, _, _ = build_picks(rows, 100.0, 7)
    assert picks["conservative"]["strike"] == 105


def test_fallback_prefers_unused_strike():
    # Three rows: aggressive takes the $108 strike, middle takes
    # the $100 strike. The $105 strike is too far from the
    # conservative band to be a fallback, so conservative stays
    # empty instead of repeating a trade under a different label.
    rows = [
        _row(100, 4.00, 0.40),
        _row(105, 2.00, 0.45),
        _row(108, 1.00, 0.50),
    ]
    picks, fallbacks, reasons = build_picks(rows, 100.0, 37)
    assert picks["aggressive"]["strike"] == 108
    assert picks["middle"]["strike"] == 100
    assert picks["conservative"] is None
    assert reasons["conservative"] == "no_band_strike"
    assert picks["conservative"] is None
    assert "aggressive" in fallbacks
    assert len({p["strike"] for p in picks.values() if p}) == 2
