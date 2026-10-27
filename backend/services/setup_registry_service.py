"""
Setup registry service.

Handles status enforcement, seeding the six registered setups, and
reading the backtest verdict from the report file on disk.
"""
import os
import logging
import re

logger = logging.getLogger(__name__)

VALID_STATUSES = {"LIVE", "SHADOW", "RETIRED"}

# Absolute path to the backtests directory
_HERE = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "backtests"))


# ---------------------------------------------------------------------------
# Status enforcement
# ---------------------------------------------------------------------------

def _read_report_fields(report_file: str) -> tuple[str | None, str | None]:
    """
    Parse a backtest markdown report and return (verdict, data_source_stamp).
    verdict is the word after '**' on the Verdict line (e.g. PASSES, SHADOW ONLY, FAILS).
    data_source_stamp is the text after '**Data source**: '.
    Returns (None, None) if the file is missing or unparseable.
    """
    path = os.path.join(BACKTESTS_DIR, os.path.basename(report_file))
    if not os.path.isfile(path):
        return None, None
    try:
        text = open(path).read()
    except Exception as e:
        logger.warning("Could not read backtest file %s: %s", path, e)
        return None, None

    verdict = None
    data_source = None

    for line in text.splitlines():
        if line.startswith("**Data source**:"):
            data_source = line.split(":", 1)[1].strip()
        m = re.match(r"^\*\*(.+?)\*\*", line)
        if m and not line.startswith("**Data source**"):
            candidate = m.group(1)
            if candidate in ("PASSES", "SHADOW ONLY", "FAILS"):
                verdict = candidate

    return verdict, data_source


def _qualifies_for_live(verdict: str | None, data_source: str | None) -> bool:
    """
    A setup may be LIVE only when:
      - The verdict is PASSES
      - The data source stamp starts with REAL (not SYNTHETIC, not MODELED)
    """
    if verdict != "PASSES":
        return False
    if data_source is None:
        return False
    return data_source.strip().upper().startswith("REAL")


def enforce_status(
    requested_status: str,
    verdict: str | None,
    data_source: str | None,
    setup_name: str = "",
) -> str:
    """
    Apply the status enforcement rule and return the allowed status.
    Raises ValueError if the caller tries to set LIVE when the rule is not met.
    """
    if requested_status not in VALID_STATUSES:
        raise ValueError(f"Unknown status '{requested_status}'. Must be one of {VALID_STATUSES}.")

    if requested_status == "LIVE":
        if not _qualifies_for_live(verdict, data_source):
            raise ValueError(
                f"Cannot set '{setup_name or 'setup'}' to LIVE. "
                "LIVE requires a backtest stamped with real data (Data source: REAL ...) "
                f"and a verdict of PASSES. "
                f"Current verdict: {verdict!r}, data source: {data_source!r}. "
                "Synthetic or modeled-only results cap the status at SHADOW."
            )

    return requested_status


def resolve_status_from_file(report_file: str | None) -> tuple[str, str | None, str | None]:
    """
    Derive the correct status for a setup given its report file.
    Returns (status, verdict, data_source_stamp).
    """
    if not report_file:
        return "SHADOW", None, None
    verdict, data_source = _read_report_fields(report_file)
    if verdict is None:
        return "SHADOW", None, None
    if _qualifies_for_live(verdict, data_source):
        return "LIVE", verdict, data_source
    return "SHADOW", verdict, data_source


def get_status(db, setup_key: str) -> str:
    """
    Registry status for a setup key, re-enforced against its backtest
    file. Returns "SHADOW" when the setup has no registry row yet (an
    unregistered setup never counts as LIVE). This is the single
    gate for LIVE alerting: Directional and Champions picks check it
    before any Challenge or Telegram alert is created.
    """
    try:
        row = get_setup(db, setup_key)
    except Exception:
        return "SHADOW"
    if row is None:
        return "SHADOW"
    return row.status or "SHADOW"


def is_live(db, setup_key: str) -> bool:
    """True only when the registry says the setup is LIVE."""
    return get_status(db, setup_key) == "LIVE"


# ---------------------------------------------------------------------------
# Registry definitions
# ---------------------------------------------------------------------------

# Setups retired by a deliberate decision, not by a backtest file.
# seed_registry and reenforce_statuses never revive these rows.
RETIRED_SETUP_KEYS = {"post_earnings_drift"}

_SETUPS = [
    {
        "setup_key": "quality_pullback",
        "name": "Quality Pullback",
        "job": "buy_and_hold",
        "recipe": (
            "Universe: S&P 500 + Dividend Achievers with at least 5 years of history.\n"
            "Signal (evaluated at close of day T):\n"
            "  - Price within 2% above the 50-day or 200-day moving average\n"
            "  - 200-day MA is rising (today's value above value 20 days ago)\n"
            "  - RSI(14) below 55 now, and was above 60 within the prior 20 sessions\n"
            "    (pulled back from momentum, not a broken stock)\n"
            "  - Volume below the 20-day average volume (quiet pullback, not distribution)\n"
            "  - No earnings within 5 days\n"
            "  - SPY above its 200-day MA (market gate; below or unknown blocks the alert)\n"
            "Entry: next session open plus 0.05% slippage.\n"
            "Exit: stop on close below 200-day MA; target when RSI(14) exceeds 68; "
            "30-day time stop."
        ),
        "backtest_file": "backtests/quality_pullback.md",
    },
    {
        "setup_key": "premium_at_support",
        "name": "Premium at Support (Wheel)",
        "job": "wheel",
        "recipe": (
            "Universe: S&P 500 + Dividend Achievers (same quality filter as Quality Pullback).\n"
            "Signal (evaluated at close of day T):\n"
            "  - Price within 2% of the 50-day MA (above or below)\n"
            "  - 200-day MA rising\n"
            "  - IV percentile in the top third of the trailing 252-session history\n"
            "    (IV percentile from the IV store only; unknown IV blocks, no HV proxy)\n"
            "  - No earnings within 5 days\n"
            "Entry: next session open for the stock signal.\n"
            "Options trade: sell a 30-delta cash-secured put from the listed chain "
            "at the bid, nearest 21 DTE; close at 50% profit or 21 DTE; "
            "suppressed as 'no listed chain' when no listed chain is available.\n"
            "Stock exit: stop on close below 200-day MA; 30-day time stop.\n"
            "Note: live alerts are priced from the listed chain only. The "
            "backtest still models with Black-Scholes and HV, so live and "
            "backtest P&L are not on the same basis; do not promote on the "
            "backtest alone."
        ),
        "backtest_file": "backtests/premium_at_support.md",
    },
    {
        "setup_key": "volume_breakout",
        "name": "Volume-Confirmed Breakout",
        "job": "directional",
        "recipe": (
            "Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py).\n"
            "Signal (evaluated at close of day T):\n"
            "  - Close above the prior 55-day high (today excluded from the window)\n"
            "  - Volume at least 1.5 times the 20-day average volume\n"
            "  - Price above a rising 50-day MA\n"
            "  - No earnings within 5 days\n"
            "  - SPY above its 200-day MA (market gate; below or unknown blocks the alert)\n"
            "Entry: next session open plus 0.05% slippage.\n"
            "Exit: stop on close below the breakout level; target at entry plus 2 times ATR(14); "
            "15-day time stop."
        ),
        "backtest_file": "backtests/volume_breakout.md",
    },
    {
        "setup_key": "directional_options",
        "name": "Directional Options (Phase 3A)",
        "job": "directional",
        "recipe": (
            "Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py).\n"
            "Canonical directional system: DirectionalEngine, scheduled "
            "weekdays 16:30 ET (job directional_daily). OptionsEngine is "
            "research only and never fires an alert.\n"
            "Signal: DirectionalEngine builds one candidate per ticker from the "
            "listed 21 DTE chain, ranked by expiry-consistent EV per $ risked.\n"
            "P(profit) is P(stock finishes past breakeven) from the contract IV.\n"
            "Entry: listed contract premium (ask, else last trade, else fair value).\n"
            "Exit: premium stop at -50% of entry premium, target, or expiry.\n"
            "Live grading as of 2026-10-26: 64 picks, 11 settled, 0% win rate, "
            "-$10,595 option P&L. Status SHADOW until a real-data backtest "
            "passes on file. While SHADOW, candidates are journaled for "
            "grading only and are never sent as LIVE Challenge alerts."
        ),
        "backtest_file": "backtests/directional_options.md",
    },
    {
        "setup_key": "champions_ai_picks",
        "name": "Champions AI Picks",
        "job": "directional",
        "recipe": (
            "Daily picks (wheel / options / longterm strategies) from the "
            "Champions engine: a prescreened universe scored by a written "
            "quant rule (services.quant_picks.champion_score), three picks "
            "per run, Claude writes explanations only, settled on a fixed calendar "
            "horizon by strategy (30 / 21 / 90 days) on the underlying stock "
            "move, because no contract is recorded at pick time.\n"
            "Status SHADOW until the picks pass the same harness as the stock "
            "setups (real-data backtest with a PASSES verdict). While SHADOW, "
            "picks are graded in the Book scoreboard only and are never sent "
            "as LIVE Challenge alerts."
        ),
        "backtest_file": None,
    },
    {
        "setup_key": "directional_puts",
        "name": "Directional Puts (Down-Market)",
        "job": "directional",
        "recipe": (
            "Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py).\n"
            "Signal (evaluated at close of day T, in a down or volatile regime):\n"
            "  - Long puts or defined-risk bear spreads on names in a confirmed "
            "downtrend (price below a falling 50-day MA)\n"
            "  - Entry sized from the contract's own IV, with real P(profit) and "
            "dollar expectancy computed the same way as Directional calls\n"
            "  - No earnings within 5 days\n"
            "Entry: next session open.\n"
            "Exit: defined-risk spread exits at max loss or at the target; "
            "long puts exit at the target or on a trend reversal; 21-day time stop.\n"
            "Note: no backtest completed yet; status SHADOW until real-data PASSES on file."
        ),
        "backtest_file": "backtests/directional_puts.md",
    },
    {
        "setup_key": "oversold_bounce",
        "name": "Oversold Bounce in a Quality Name",
        "job": "buy_and_hold",
        "recipe": (
            "Universe: 12 Step Process passing names (quality filter from the app's screener).\n"
            "Signal (evaluated at close of day T):\n"
            "  - RSI(14) below 30 (deeply oversold on a short-term basis)\n"
            "  - Price above the 200-day MA (long-term uptrend intact)\n"
            "  - 200-day MA rising (not in a structural downtrend)\n"
            "  - No earnings within 5 days\n"
            "Entry: next session open.\n"
            "Exit: RSI(14) back above 50 (mean reversion complete); stop on close below the "
            "200-day MA; 30-day time stop.\n"
            "Note: no backtest completed yet; status SHADOW until real-data PASSES on file."
        ),
        "backtest_file": None,
    },
    {
        "setup_key": "trend_pullback_reversal",
        "name": "Trend Pullback Reversal",
        "job": "directional",
        "recipe": (
            "Universe: app directional universe.\n"
            "Signal (evaluated at close of day T):\n"
            "  - Established uptrend: price above rising 20-day and 50-day MAs\n"
            "  - Pullback to within 1% of the 20-day or 50-day MA\n"
            "  - Reversal confirmation: RSI(14) turning up from below 50 OR bullish engulfing "
            "candle at the MA level (today's close above today's open; today's open below "
            "yesterday's close; today's close above yesterday's open)\n"
            "  - No earnings within 5 days\n"
            "Entry: next session open.\n"
            "Exit: stop below the low of the signal candle (defined risk); target at entry plus 2x ATR(14); 15-day time stop.\n"
            "Note: no backtest completed yet; status SHADOW until real-data PASSES on file."
        ),
        "backtest_file": None,
    },
    {
        "setup_key": "post_earnings_drift",
        "name": "Post-Earnings Drift",
        "job": "directional",
        "recipe": (
            "Universe: any liquid name that reports earnings with a beat and raised guidance.\n"
            "Signal (evaluated on the second day after the earnings gap):\n"
            "  - Earnings beat: reported EPS above consensus estimate\n"
            "  - Guidance raised for the next quarter or full year\n"
            "  - Gap holds: second-day close above first-day close (gap not filled)\n"
            "  - IV crush confirmed: implied volatility on the second day below the "
            "30-day average IV before the event\n"
            "Entry: second session close after the earnings gap.\n"
            "Exit: target at prior high or 10% above entry; stop at the gap open (first-day "
            "open); 15-day time stop.\n"
            "Note: RETIRED, research only. The recipe requires an earnings beat "
            "and raised guidance and no reliable source for either exists in "
            "this repo, so the setup never fires."
        ),
        "backtest_file": None,
    },
]


def reenforce_statuses(db) -> list:
    """
    Re-check every registry row against its backtest file on disk and
    correct any row whose stored status no longer matches what the file
    supports (review M31: a row that is LIVE stays LIVE even if its
    backtest later fails).

    Rules:
      - RETIRED rows are never touched (a manual decision, not a file verdict).
      - Any other row is set to LIVE only when its file currently qualifies
        (real-data PASSES); otherwise it is set to SHADOW.
      - The stored verdict and data source stamp are refreshed from the
        file at the same time, so a later set_setup_status call enforces
        against current evidence, not a stale stamp.
    Returns the list of setup keys whose status changed.
    """
    from models.setup_registry import SetupRegistry

    changed = []
    dirty = False
    for row in db.query(SetupRegistry).all():
        status, verdict, data_source = resolve_status_from_file(row.backtest_file)
        if row.status == "RETIRED":
            if row.backtest_verdict != verdict or row.backtest_data_source != data_source:
                row.backtest_verdict = verdict
                row.backtest_data_source = data_source
                dirty = True
            continue
        if row.status != status or row.backtest_verdict != verdict \
                or row.backtest_data_source != data_source:
            logger.info(
                "setup_registry: re-enforcing '%s' %s -> %s (verdict=%s, data_source=%s)",
                row.setup_key, row.status, status, verdict, data_source,
            )
            row.status = status
            row.backtest_verdict = verdict
            row.backtest_data_source = data_source
            changed.append(row.setup_key)
            dirty = True
    if dirty:
        db.commit()
    return changed


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

def seed_registry(db) -> None:
    """
    Insert all nine setups into the database if they are not already there.
    Status is derived from the backtest file on disk using the enforcement rule.
    Safe to call on every startup; already-existing rows are re-enforced
    against their current backtest file (see reenforce_statuses), so a row
    never keeps a LIVE status its backtest no longer supports.
    """
    from models.setup_registry import SetupRegistry

    for defn in _SETUPS:
        existing = (
            db.query(SetupRegistry)
            .filter(SetupRegistry.setup_key == defn["setup_key"])
            .first()
        )
        if existing:
            if defn["setup_key"] in RETIRED_SETUP_KEYS and existing.status != "RETIRED":
                existing.status = "RETIRED"
                logger.info(
                    "setup_registry: retiring '%s' (deliberate decision, W4)",
                    defn["setup_key"],
                )
            continue

        if defn["setup_key"] in RETIRED_SETUP_KEYS:
            status, verdict, data_source = "RETIRED", None, None
        else:
            status, verdict, data_source = resolve_status_from_file(defn["backtest_file"])
        row = SetupRegistry(
            setup_key=defn["setup_key"],
            name=defn["name"],
            job=defn["job"],
            recipe=defn["recipe"],
            status=status,
            backtest_file=defn["backtest_file"],
            backtest_verdict=verdict,
            backtest_data_source=data_source,
        )
        db.add(row)
        logger.info(
            "setup_registry: seeded '%s' as %s (verdict=%s, data_source=%s)",
            defn["setup_key"], status, verdict, data_source,
        )

    try:
        db.commit()
    except Exception as e:
        logger.error("setup_registry: seed commit failed: %s", e)
        db.rollback()

    # Re-enforce existing rows: a backtest file may have changed since the
    # row was seeded (new run, failed verdict, or a file removed).
    reenforce_statuses(db)


# ---------------------------------------------------------------------------
# Utility read functions
# ---------------------------------------------------------------------------

def get_all_setups(db) -> list:
    from models.setup_registry import SetupRegistry
    # Re-enforce on every load (review M31): a backtest file may have
    # changed since the row was seeded, and a LIVE row must not survive
    # a backtest that later fails.
    reenforce_statuses(db)
    return db.query(SetupRegistry).order_by(SetupRegistry.id).all()


def get_setup(db, setup_key: str):
    from models.setup_registry import SetupRegistry
    # Re-enforce on every load (review M31); see get_all_setups.
    reenforce_statuses(db)
    return (
        db.query(SetupRegistry)
        .filter(SetupRegistry.setup_key == setup_key)
        .first()
    )


def set_setup_status(db, setup_key: str, new_status: str) -> dict:
    """
    Update a setup's status. Enforces the LIVE rule against the CURRENT
    backtest file on disk (re-read here, not the stored stamp, so a stale
    verdict cannot authorize a promotion).
    Returns {"ok": True, "status": "LIVE"} or raises ValueError.
    """
    from models.setup_registry import SetupRegistry

    row = db.query(SetupRegistry).filter(SetupRegistry.setup_key == setup_key).first()
    if row is None:
        raise ValueError(f"Setup '{setup_key}' not found in registry.")

    _, verdict, data_source = resolve_status_from_file(row.backtest_file)
    row.backtest_verdict = verdict
    row.backtest_data_source = data_source
    allowed = enforce_status(
        new_status,
        verdict,
        data_source,
        setup_name=row.name,
    )
    row.status = allowed
    db.commit()
    return {"ok": True, "status": row.status, "setup_key": setup_key}
