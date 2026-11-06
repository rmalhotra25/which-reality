"""Tests for AI Picks: parsing, Polygon price override, and separation.

Separation is the point of this section, so it is tested, not just
documented: the ai_picks service and router never import the setup
registry, the backtest harness, or the Book scoreboard, and a
serialized run carries no LIVE status and no setup key.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_picks import (
    DEFAULT_TICKERS,
    DISCLAIMER,
    _clean_tickers,
    _bars_summary,
    apply_polygon_prices,
    build_context,
    build_prompt,
    parse_ai_picks_response,
    serialize_run,
)


def _good_json():
    return json.dumps({
        "options_ideas": [
            {
                "ticker": "MSFT", "option_type": "call", "action": "buy",
                "strike": 550, "expiry": "2026-12-18",
                "entry_price": 5.20, "exit_price": 9.00, "stop_price": 2.50,
                "plan_text": "Buy in at $5.20, get out at $9.00.",
                "reasoning": "Breaking out on volume.",
                "key_risks": ["Gap down", "IV crush"],
            },
            {
                "ticker": "BAD!", "option_type": "call", "action": "buy",
                "strike": 100, "expiry": "2026-12-18",
            },
            {
                "ticker": "TSLA", "option_type": "put", "action": "sell",
                "strike": 0, "expiry": "2026-12-18",
            },
        ],
        "long_term_ideas": [
            {"ticker": "MSFT", "company_name": "Microsoft", "current_price": 999.99,
             "thesis": "Cloud growth.", "key_risks": ["Competition"], "upside_case": "Azure keeps growing."}
        ] + [
            {"ticker": t, "company_name": f"Company {t}", "thesis": "Cheap.",
             "key_risks": ["Risk"], "upside_case": "Upside."}
            for t in ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF",
                      "GGGG", "HHHH", "IIII", "JJJJ", "KKKK", "LLLL"]
        ],
    })


def test_parse_keeps_valid_ideas_and_drops_bad_ones():
    out = parse_ai_picks_response(_good_json())
    assert out["parse_error"] is None
    assert len(out["options_ideas"]) == 1
    idea = out["options_ideas"][0]
    assert idea["ticker"] == "MSFT" and idea["option_type"] == "call"
    assert idea["action"] == "buy" and idea["strike"] == 550
    assert idea["entry_price"] == 5.20 and idea["exit_price"] == 9.00
    assert idea["ai_generated"] is True
    # Long-term list is truncated to 10, not padded.
    assert len(out["long_term_ideas"]) == 10


def test_parse_invalid_json_returns_empty_with_error():
    out = parse_ai_picks_response("not json at all {{{")
    assert out["options_ideas"] == [] and out["long_term_ideas"] == []
    assert out["parse_error"] is not None


def test_parse_missing_sections_returns_empty_lists():
    out = parse_ai_picks_response(json.dumps({"hello": "world"}))
    assert out["options_ideas"] == [] and out["long_term_ideas"] == []
    assert out["parse_error"] is None


def test_polygon_price_overrides_ai_claimed_price():
    out = parse_ai_picks_response(_good_json())
    fixed = apply_polygon_prices(out, {"MSFT": 512.34})
    lt = fixed["long_term_ideas"][0]
    assert lt["current_price"] == 512.34
    assert lt["price_source"] == "polygon"
    opt = fixed["options_ideas"][0]
    assert opt["reference_price"] == 512.34
    assert opt["price_source"] == "polygon"


def test_missing_polygon_price_leaves_claimed_but_labels_it():
    out = parse_ai_picks_response(_good_json())
    fixed = apply_polygon_prices(out, {})
    lt = fixed["long_term_ideas"][0]
    assert lt["current_price"] == 999.99
    assert lt["price_source"] == "ai_claimed"
    opt = fixed["options_ideas"][0]
    assert opt["reference_price"] is None
    assert opt["price_source"] == "unavailable"


def test_missing_price_stays_null_and_unavailable():
    payload = {"options_ideas": [], "long_term_ideas": [
        {"ticker": "XYZ", "company_name": "Xyz", "current_price": None,
         "price_source": "ai_claimed", "thesis": "t", "key_risks": [],
         "upside_case": "u", "ai_generated": True},
    ], "parse_error": None}
    fixed = apply_polygon_prices(payload, {})
    assert fixed["long_term_ideas"][0]["current_price"] is None
    assert fixed["long_term_ideas"][0]["price_source"] == "unavailable"


def test_clean_tickers_rejects_junk_and_caps_at_12():
    # "X" is a real one-letter ticker, so it stays; "AAPL!" and
    # "BRK.B" are not plain ticker symbols and are dropped.
    assert _clean_tickers(["msft", "AAPL!", "msft", "BRK.B", "x"]) == ["MSFT", "X"]
    assert len(_clean_tickers([f"T{i}" for i in range(20)])) <= 12
    assert _clean_tickers([]) == []


def test_bars_summary_computes_returns_and_range():
    bars = [{"c": 100 + i, "v": 1000} for i in range(35)]
    s = _bars_summary(bars)
    assert s["price"] == 134
    assert s["return_5d_pct"] == round((134 / 129 - 1) * 100, 1)
    assert s["high_35d"] == 134 and s["low_35d"] == 100


def test_build_context_uses_fetchers_and_never_invents():
    def snaps(tickers):
        return {"MSFT": {"price": 500.0, "change_pct": 1.5, "prev_close": 492.0, "volume": 1000}}
    def bars(ticker, days=35):
        return [{"c": 100 + i, "v": 1000} for i in range(35)]
    def news(ticker, limit=3):
        return [{"title": "MSFT beats", "published_at": "2026-11-05", "publisher": "Wire"}]
    ctx = build_context(["MSFT"], fetchers={
        "snapshots_batch": snaps, "ohlcv_bars": bars, "news": news,
        "vix": lambda: 18.5, "chain_snapshot": lambda *a, **k: [],
    })
    assert ctx["vix"] == 18.5
    row = ctx["tickers"][0]
    assert row["price"] == 500.0
    assert row["news"][0]["title"] == "MSFT beats"
    assert row["chain_near_money"] == []


def test_build_context_survives_failed_fetches():
    def boom(*a, **k):
        raise RuntimeError("Polygon down")
    ctx = build_context(["MSFT"], fetchers={
        "snapshots_batch": boom, "ohlcv_bars": boom, "news": boom,
        "vix": boom, "chain_snapshot": boom,
    })
    assert ctx["tickers"][0]["price"] is None
    assert ctx["tickers"][0]["news"] == []
    assert ctx["vix"] is None


def test_prompt_asks_for_json_only_and_both_lists():
    system, user = build_prompt({"tickers": [{"ticker": "MSFT", "price": 500.0}], "vix": 18.0})
    assert "Respond ONLY with a valid JSON object" in system
    assert "options_ideas" in user and "long_term_ideas" in user
    assert "exactly 10 stocks" in user


def test_disclaimer_text_is_present():
    assert "not based on the app's backtested rules" in DISCLAIMER
    assert "not recommendations" in DISCLAIMER


def test_default_tickers_are_liquid_names():
    assert len(DEFAULT_TICKERS) == 10
    assert len(set(DEFAULT_TICKERS)) == 10


def test_serialized_run_has_no_live_status_or_setup_key():
    class FakeRun:
        id = 1
        created_at = None
        tickers = '["MSFT"]'
        status = "completed"
        error = None
        payload = json.dumps({"options_ideas": [], "long_term_ideas": []})
    out = serialize_run(FakeRun())
    blob = json.dumps(out)
    assert "LIVE" not in blob
    assert "setup_key" not in blob
    assert "setup_registry" not in blob
    assert out["disclaimer"] == DISCLAIMER
    assert out["status"] == "completed"


def test_ai_picks_modules_do_not_import_quant_enforcement():
    import ast
    import pathlib
    service = pathlib.Path(__file__).resolve().parents[1].joinpath("services/ai_picks.py").read_text()
    router = pathlib.Path(__file__).resolve().parents[1].joinpath("routers/ai_picks.py").read_text()
    for text in (service, router):
        tree = ast.parse(text)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        joined = "\n".join(sorted(imported))
        assert "rule_registry" not in joined
        assert "setup_registry" not in joined
        assert "backtest_harness" not in joined
        assert "scoreboard" not in joined
        assert "get_status" not in joined
        # And no runtime reference to a LIVE status either.
        assert '"LIVE"' not in text and "'LIVE'" not in text
