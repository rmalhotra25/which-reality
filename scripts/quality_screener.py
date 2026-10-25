#!/usr/bin/env python3
"""
Quality screener, elimination first.

Starts from every US-listed stock and removes names that fail any of the
five Tom Nash pre-screen kills (screenshot, Investing Mastery):

  01  Market cap under $1 billion
  02  Short interest above 20 percent
  03  Negative free cash flow
  04  More debt than cash (without a good explanation)
  05  Two or more earnings misses in the last four quarters

What survives is ranked by Rule of 40 (revenue growth % + FCF margin %),
highest first. The point is buying a quality company, so the screener
eliminates first and ranks only what is left.

Data sources (no API keys needed):
  - TradingView scanner API for market cap, FCF, debt, cash, FCF margin,
    operating margin, exchange.
  - yfinance for short interest (% of float), revenue growth, and earnings
    surprises (last four reported quarters).

A name that cannot be verified on a rule is NOT passed silently. It is
listed separately as unverified so nothing hides behind missing data.

Optional extra kills from the Nash Step 3 notes (off by default):
  --with-margin-kill   also remove operating margin below 20%

Usage:
  python3 quality_screener.py [--with-margin-kill] [--top N] [--out-dir DIR]

Outputs (in the out dir, default ./results):
  quality_screener_results.md   funnel counts plus the top N ranked survivors
  quality_screener_results.csv  every survivor with every field
  quality_screener_unverified.csv  names dropped only because data was missing
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# ---------------------------------------------------------------- config
MARKET_CAP_MIN = 1_000_000_000      # rule 01: under $1B is out
SHORT_MAX = 0.20                    # rule 02: short interest above 20% is out
MAX_MISSES = 1                      # rule 05: two or more misses in last 4 is out
EXCHANGES = {"NASDAQ", "NYSE"}      # US-listed only
TV_URL = "https://scanner.tradingview.com/america/scan"
TV_COLUMNS = [
    "name",
    "exchange",
    "market_cap_basic",
    "free_cash_flow_ttm",
    "total_debt",
    "cash_n_short_term_invest_fq",
    "free_cash_flow_margin_ttm",
    "operating_margin_ttm",
]
YF_WORKERS = 15
YF_TIMEOUT = 45


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------- TradingView scan
def tv_scan():
    """Fetch every US stock with the fundamental columns, paged.

    Sorted by name so paging is stable: without an explicit sort the
    scanner can return the same symbol twice and skip others entirely
    when the underlying data shifts between page requests.
    """
    rows = []
    start = 0
    page = 1000
    while True:
        body = json.dumps({
            "symbols": {"query": {"types": ["stock"]}, "tickers": []},
            "columns": TV_COLUMNS,
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "options": {"lang": "en"},
            "range": [start, start + page],
        }).encode()
        req = urllib.request.Request(
            TV_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        batch = data.get("data", [])
        total = data.get("totalCount", 0)
        for item in batch:
            d = item.get("d", [])
            rows.append(dict(zip(TV_COLUMNS, d)))
        log(f"TradingView page {start}-{start + len(batch)} of {total}")
        start += len(batch)
        if start >= total or not batch:
            break
    seen = set()
    unique = []
    for r in rows:
        key = (r.get("exchange"), r.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    log(f"Deduped {len(rows)} rows to {len(unique)} unique listings")
    return unique


def tv_filter(rows):
    """Rules 01, 03, 04 on TradingView data. Returns (survivors, funnel)."""
    funnel = {"universe": len(rows)}
    survivors = []
    for r in rows:
        if r.get("exchange") not in EXCHANGES:
            continue
        funnel["us_listed"] = funnel.get("us_listed", 0) + 1
        mcap = r.get("market_cap_basic")
        if mcap is None or mcap < MARKET_CAP_MIN:
            continue
        funnel["rule01_market_cap"] = funnel.get("rule01_market_cap", 0) + 1
        fcf = r.get("free_cash_flow_ttm")
        if fcf is None or fcf <= 0:
            continue
        funnel["rule03_fcf_positive"] = funnel.get("rule03_fcf_positive", 0) + 1
        debt = r.get("total_debt")
        cash = r.get("cash_n_short_term_invest_fq")
        if debt is None or cash is None or cash <= debt:
            continue
        funnel["rule04_cash_over_debt"] = funnel.get("rule04_cash_over_debt", 0) + 1
        survivors.append(r)
    return survivors, funnel


# ------------------------------------------------------------- yfinance
def yf_check(ticker):
    """Rules 02 and 05 plus revenue growth, for one ticker.

    Returns a dict with short_pct, revenue_growth, misses, and an
    unverified reason when a rule could not be checked.
    """
    import yfinance as yf

    out = {"ticker": ticker, "short_pct": None, "revenue_growth": None,
           "misses": None, "unverified": None}
    # yfinance wants class shares as BRK-A, not BRK.A
    yf_ticker = ticker.replace(".", "-")
    try:
        t = yf.Ticker(yf_ticker)
        info = t.info or {}
    except Exception as exc:
        out["unverified"] = f"info fetch failed: {exc}"
        return out
    sp = info.get("shortPercentOfFloat")
    if sp is not None:
        try:
            out["short_pct"] = float(sp)
        except (TypeError, ValueError):
            pass
    rg = info.get("revenueGrowth")
    if rg is not None:
        try:
            out["revenue_growth"] = float(rg)
        except (TypeError, ValueError):
            pass
    try:
        ed = t.earnings_dates
    except Exception as exc:
        out["unverified"] = f"earnings fetch failed: {exc}"
        return out
    misses = None
    if ed is not None and not ed.empty and "Surprise(%)" in ed.columns:
        reported = ed.dropna(subset=["Reported EPS", "EPS Estimate"])
        last4 = reported.tail(4)
        if len(last4) >= 4:
            misses = int((last4["Surprise(%)"] < 0).sum())
    out["misses"] = misses
    if out["short_pct"] is None:
        out["unverified"] = "no short interest data"
    elif misses is None:
        out["unverified"] = "fewer than 4 reported quarters with estimates"
    return out


def yf_filter(survivors):
    """Rules 02 and 05 on the TradingView survivors, threaded."""
    enriched = []
    unverified = []
    funnel = {"tv_survivors": len(survivors)}
    with ThreadPoolExecutor(max_workers=YF_WORKERS) as pool:
        futures = {pool.submit(yf_check, r["name"]): r for r in survivors}
        done = 0
        for fut in as_completed(futures):
            row = futures[fut]
            done += 1
            if done % 250 == 0:
                log(f"yfinance {done}/{len(survivors)} checked")
            try:
                res = fut.result(timeout=YF_TIMEOUT)
            except Exception as exc:
                unverified.append({**row, "unverified": f"check timed out: {exc}"})
                continue
            merged = {**row, **res}
            if res.get("unverified"):
                unverified.append(merged)
                continue
            if res["short_pct"] > SHORT_MAX:
                continue
            funnel["rule02_short_interest"] = funnel.get("rule02_short_interest", 0) + 1
            if res["misses"] is not None and res["misses"] > MAX_MISSES:
                continue
            funnel["rule05_earnings_misses"] = funnel.get("rule05_earnings_misses", 0) + 1
            enriched.append(merged)
    return enriched, unverified, funnel


# ---------------------------------------------------------------- ranking
def rule_of_40(row):
    rg = row.get("revenue_growth")
    fcf_margin = row.get("free_cash_flow_margin_ttm")
    if rg is None or fcf_margin is None:
        return None
    return rg * 100.0 + fcf_margin


def rank_survivors(enriched):
    for row in enriched:
        row["rule_of_40"] = rule_of_40(row)
    ranked = [r for r in enriched if r.get("rule_of_40") is not None]
    ranked.sort(key=lambda r: r["rule_of_40"], reverse=True)
    return ranked


# ---------------------------------------------------------------- outputs
def write_outputs(ranked, unverified, funnel, out_dir, top_n, with_margin_kill):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md_path = os.path.join(out_dir, "quality_screener_results.md")
    csv_path = os.path.join(out_dir, "quality_screener_results.csv")
    unv_path = os.path.join(out_dir, "quality_screener_unverified.csv")

    funnel_lines = [
        ("Universe (TradingView US stocks)", funnel.get("universe", 0)),
        ("NASDAQ / NYSE listed", funnel.get("us_listed", 0)),
        ("01 Market cap $1B or more", funnel.get("rule01_market_cap", 0)),
        ("03 Free cash flow positive", funnel.get("rule03_fcf_positive", 0)),
        ("04 Cash above total debt", funnel.get("rule04_cash_over_debt", 0)),
        ("02 Short interest 20% or less", funnel.get("rule02_short_interest", 0)),
        ("05 Fewer than 2 misses in last 4 quarters", funnel.get("rule05_earnings_misses", 0)),
    ]
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "ticker", "exchange", "market_cap_usd",
                    "fcf_ttm_usd", "total_debt_usd", "cash_usd",
                    "fcf_margin_pct", "revenue_growth_pct",
                    "short_pct", "earnings_misses_last4", "rule_of_40"])
        for i, r in enumerate(ranked, 1):
            w.writerow([
                i, r["name"], r.get("exchange"),
                round(r["market_cap_basic"]) if r.get("market_cap_basic") else "",
                round(r["free_cash_flow_ttm"]) if r.get("free_cash_flow_ttm") else "",
                round(r["total_debt"]) if r.get("total_debt") is not None else "",
                round(r["cash_n_short_term_invest_fq"]) if r.get("cash_n_short_term_invest_fq") is not None else "",
                round(r["free_cash_flow_margin_ttm"], 1) if r.get("free_cash_flow_margin_ttm") is not None else "",
                round(r["revenue_growth"] * 100, 1) if r.get("revenue_growth") is not None else "",
                round(r["short_pct"] * 100, 2) if r.get("short_pct") is not None else "",
                r.get("misses", ""),
                round(r["rule_of_40"], 1),
            ])
    with open(unv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "reason"])
        for r in unverified:
            w.writerow([r.get("name"), r.get("unverified", "")])

    top = ranked[:top_n]
    with open(md_path, "w") as fh:
        fh.write("# Quality screener results\n\n")
        fh.write(f"Run: {stamp}\n\n")
        fh.write("Elimination first, then rank what survives by Rule of 40 ")
        fh.write("(revenue growth % + FCF margin %).\n\n")
        fh.write("Rules: market cap $1B or more; short interest 20% or less; ")
        fh.write("free cash flow positive; cash above total debt; fewer than 2 ")
        fh.write("earnings misses in the last 4 quarters.")
        if with_margin_kill:
            fh.write(" Extra kill applied: operating margin below 20% removed.")
        fh.write("\n\n## Funnel\n\n")
        for label, count in funnel_lines:
            fh.write(f"- {label}: {count}\n")
        fh.write(f"- Unverified (missing data, excluded, listed separately): {len(unverified)}\n")
        fh.write(f"- Final survivors: {len(ranked)}\n\n")
        fh.write(f"## Top {len(top)} by Rule of 40\n\n")
        fh.write("| Rank | Ticker | Rule of 40 | Rev growth | FCF margin | Short % | Misses |\n")
        fh.write("|---:|---|---:|---:|---:|---:|---:|\n")
        for i, r in enumerate(top, 1):
            fh.write(
                f"| {i} | {r['name']} | {r['rule_of_40']:.1f} | "
                f"{r['revenue_growth'] * 100:.1f}% | "
                f"{r['free_cash_flow_margin_ttm']:.1f}% | "
                f"{r['short_pct'] * 100:.2f}% | {r['misses']} |\n")
        fh.write("\nFull survivor list with all fields: quality_screener_results.csv\n")
        fh.write("Names dropped only for missing data: quality_screener_unverified.csv\n")
    return md_path, csv_path, unv_path


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Elimination-first quality screener")
    ap.add_argument("--with-margin-kill", action="store_true",
                    help="also remove operating margin below 20%")
    ap.add_argument("--top", type=int, default=50, help="names in the top table")
    ap.add_argument("--out-dir", default="results", help="output directory")
    args = ap.parse_args()

    log("Step 1: TradingView scan")
    rows = tv_scan()
    log(f"Step 2: TradingView filters (rules 01, 03, 04), {len(rows)} rows")
    survivors, funnel_tv = tv_filter(rows)
    log(f"After TradingView filters: {len(survivors)} survivors")
    if args.with_margin_kill:
        before = len(survivors)
        survivors = [r for r in survivors
                     if r.get("operating_margin_ttm") is not None
                     and r["operating_margin_ttm"] >= 20]
        funnel_tv["extra_margin_kill"] = len(survivors)
        log(f"Margin kill applied: {before} -> {len(survivors)}")
    log("Step 3: yfinance checks (rules 02, 05) on survivors")
    enriched, unverified, funnel_yf = yf_filter(survivors)
    funnel = {**funnel_tv, **funnel_yf}
    log(f"After yfinance filters: {len(enriched)} survivors, "
        f"{len(unverified)} unverified")
    log("Step 4: rank by Rule of 40")
    ranked = rank_survivors(enriched)
    log(f"Ranked: {len(ranked)}")
    md, csv_path, unv = write_outputs(ranked, unverified, funnel,
                                      args.out_dir, args.top,
                                      args.with_margin_kill)
    log(f"Wrote {md}")
    log(f"Wrote {csv_path}")
    log(f"Wrote {unv}")
    print("\nTop 10 by Rule of 40:")
    for i, r in enumerate(ranked[:10], 1):
        print(f"  {i:2d}. {r['name']:6s} {r['rule_of_40']:7.1f}  "
              f"rev {r['revenue_growth'] * 100:6.1f}%  "
              f"fcf margin {r['free_cash_flow_margin_ttm']:5.1f}%  "
              f"short {r['short_pct'] * 100:5.2f}%  misses {r['misses']}")


if __name__ == "__main__":
    main()
