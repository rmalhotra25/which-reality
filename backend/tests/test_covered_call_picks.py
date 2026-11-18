import sys
from pathlib import Path

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
    rows = [
        _row(90, 12.00, 0.70),
        _row(95, 8.00, 0.60),
        _row(100, 4.00, 0.40),
        _row(105, 2.00, 0.35),
        _row(110, 1.00, 0.20),
        _row(115, 0.50, 0.18),
    ]
    picks, fallbacks = build_picks(rows, 100.0, 37)
    assert picks["aggressive"]["strike"] == 90
    assert picks["middle"]["strike"] == 100
    assert picks["conservative"]["strike"] == 110
    assert fallbacks == []
    assert picks["aggressive"]["premium_per_contract"] == 1200.00
    assert picks["aggressive"]["premium_yield_pct"] == 12.0
    assert picks["aggressive"]["breakeven"] == 102.0
    assert picks["middle"]["distance_to_strike_pct"] == 0.0


def test_band_fallback_uses_nearest_strike_and_flags_it():
    rows = [_row(100, 4.00, 0.40), _row(110, 1.00, 0.50)]
    picks, fallbacks = build_picks(rows, 100.0, 37)
    assert picks["conservative"]["strike"] == 100
    assert picks["conservative"]["band_fallback"] is True
    assert "conservative" in fallbacks


def test_no_chain_rows_means_no_picks_not_fabricated():
    picks, fallbacks = build_picks([], 100.0, 37)
    assert picks == {"aggressive": None, "middle": None, "conservative": None}
    assert fallbacks == []


def test_bid_not_last_trade_pricing():
    rows = [_row(100, 2.00, 0.40, last_trade=9.99)]
    picks, _ = build_picks(rows, 100.0, 37)
    assert picks["middle"]["bid_per_share"] == 2.00
    assert picks["middle"]["premium_per_contract"] == 200.00


def test_rows_without_bid_or_delta_are_excluded():
    rows = [
        _row(100, 0.0, 0.40),
        _row(105, 2.00, None),
        _row(110, 1.00, 0.20),
    ]
    row, fallback = select_tier(rows, 0.30, 0.45, 0.375)
    assert row["strike"] == 110
    assert fallback is True
    picks, _ = build_picks(rows, 100.0, 37)
    assert picks["conservative"]["strike"] == 110
    assert picks["middle"]["band_fallback"] is True


def test_missing_greeks_stay_missing():
    rows = [_row(100, 4.00, 0.40, gamma=None, vega=None, theta_seller=None)]
    picks, _ = build_picks(rows, 100.0, 37)
    assert picks["middle"]["gamma"] is None
    assert picks["middle"]["vega"] is None
    assert picks["middle"]["theta_seller"] is None


def test_default_expiry_prefers_30_to_45_window():
    expiries = [
        {"expiry": "2026-11-20", "dte": 18},
        {"expiry": "2026-12-11", "dte": 39},
        {"expiry": "2026-12-04", "dte": 32},
        {"expiry": "2027-01-15", "dte": 74},
    ]
    assert default_expiry(expiries)["expiry"] == "2026-12-11"
    assert default_expiry([{"expiry": "2026-11-20", "dte": 18}])["dte"] == 18
    assert default_expiry([]) is None


def test_annualized_yield_and_shares_total():
    rows = [_row(110, 1.00, 0.20)]
    picks, _ = build_picks(rows, 100.0, 37, shares_owned=250)
    assert picks["conservative"]["contracts_covered"] == 2
    assert picks["conservative"]["total_premium_for_shares"] == 200.00
    assert picks["conservative"]["annualized_yield_pct"] == round(1.0 * 365 / 37, 1)


def test_deep_itm_stale_quote_is_rejected():
    # AAPL Dec 18 2026, live: the only row with a positive bid was
    # the $35 strike on a $351.91 stock, bid $284.80, delta 1.0.
    # The strike sits 90% below the price, so no tier may use it.
    rows = [_row(35, 284.80, 1.0)]
    picks, fallbacks = build_picks(rows, 351.91, 30)
    assert picks == {"aggressive": None, "middle": None, "conservative": None}
    assert fallbacks == []


def test_itm_bid_below_intrinsic_rejected_but_fair_bid_passes():
    # Strike $90 on a $100 stock: intrinsic $10. A $5.00 bid sits
    # $5 below intrinsic, far past the $2 tolerance, so it is a
    # stale quote and no tier may use it.
    rows = [_row(90, 5.00, 1.0)]
    picks, _ = build_picks(rows, 100.0, 37)
    assert picks["aggressive"] is None
    # A $9.50 bid sits $0.50 below intrinsic, inside tolerance.
    rows = [_row(90, 9.50, 1.0)]
    picks, fallbacks = build_picks(rows, 100.0, 37)
    assert picks["aggressive"]["strike"] == 90
    assert picks["aggressive"]["band_fallback"] is True


def test_fallback_prefers_unused_strike():
    # Three rows: aggressive takes the $115 strike, middle takes
    # the $100 strike. The old fallback handed conservative the
    # $100 strike again; it must prefer the unused $105 strike.
    rows = [
        _row(100, 4.00, 0.40),
        _row(105, 2.00, 0.45),
        _row(115, 1.00, 0.50),
    ]
    picks, fallbacks = build_picks(rows, 100.0, 37)
    assert picks["aggressive"]["strike"] == 115
    assert picks["middle"]["strike"] == 100
    assert picks["conservative"]["strike"] == 105
    assert picks["conservative"]["band_fallback"] is True
    assert len({p["strike"] for p in picks.values() if p}) == 3
