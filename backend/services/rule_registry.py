"""
Rule registry service (P1 determinism).

One row per alert or notification rule in the app, extending the setup
registry pattern instead of building a second system. The 9 setups from
the setup registry become alert.<setup_key> rules, and the 5 Challenge
alert types become challenge.* rules. No new rules are invented in this
phase: this registers what already exists.

Rules not in the registry cannot fire or notify. A startup check
(verify_rules) fails visibly when a LIVE rule has no implementing
function or its thresholds differ from the row.

Thresholds live as numbers in trigger_json. The check compares the
mapped thresholds against the module-level constants in the
implementing code (services.alert_engine, services.challenge_service),
so a row and its code cannot drift apart silently.
"""
import importlib
import json
import logging

logger = logging.getLogger(__name__)

VALID_STATUSES = {"LIVE", "SHADOW", "RETIRED"}

# rule_key -> {threshold name in trigger_json: (module, constant name)}
# Only thresholds that exist as a named constant in code are checked.
# Anything else in trigger_json is documentation of the written rule.
THRESHOLD_CHECKS = {
    "alert.quality_pullback": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "risk_pct": ("services.alert_engine", "RISK_PCT_PER_TRADE"),
        "near_ma_pct": ("services.alert_engine", "QP_NEAR_MA_PCT"),
        "rsi_lt": ("services.alert_engine", "QP_RSI_LT"),
        "rsi_was_above": ("services.alert_engine", "QP_RSI_WAS_ABOVE"),
        "rsi_exit": ("services.alert_engine", "QP_RSI_EXIT"),
        "time_stop_days": ("services.alert_engine", "QP_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
    "alert.premium_at_support": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "near_ma_pct": ("services.alert_engine", "PAS_NEAR_MA_PCT"),
        "iv_pct_min": ("services.alert_engine", "PAS_IV_PCT_MIN"),
        "target_dte": ("services.alert_engine", "PAS_TARGET_DTE"),
        "time_stop_days": ("services.alert_engine", "PAS_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
    "alert.volume_breakout": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "risk_pct": ("services.alert_engine", "RISK_PCT_PER_TRADE"),
        "prior_high_days": ("services.alert_engine", "VB_PRIOR_HIGH_DAYS"),
        "vol_mult": ("services.alert_engine", "VB_VOL_MULT"),
        "atr_target_mult": ("services.alert_engine", "VB_ATR_TARGET_MULT"),
        "time_stop_days": ("services.alert_engine", "VB_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
    "alert.oversold_bounce": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "risk_pct": ("services.alert_engine", "RISK_PCT_PER_TRADE"),
        "rsi_lt": ("services.alert_engine", "OB_RSI_LT"),
        "rsi_exit": ("services.alert_engine", "OB_RSI_EXIT"),
        "time_stop_days": ("services.alert_engine", "OB_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
    "alert.trend_pullback_reversal": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "risk_pct": ("services.alert_engine", "RISK_PCT_PER_TRADE"),
        "near_ma_pct": ("services.alert_engine", "TPR_NEAR_MA_PCT"),
        "rsi_band_low": ("services.alert_engine", "TPR_RSI_BAND_LOW"),
        "rsi_band_high": ("services.alert_engine", "TPR_RSI_BAND_HIGH"),
        "rsi_prev_lt": ("services.alert_engine", "TPR_RSI_PREV_LT"),
        "atr_target_mult": ("services.alert_engine", "TPR_ATR_TARGET_MULT"),
        "time_stop_days": ("services.alert_engine", "TPR_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
    "alert.post_earnings_drift": {
        "earnings_block_days": ("services.alert_engine", "EARNINGS_BLOCK_DAYS"),
        "risk_pct": ("services.alert_engine", "RISK_PCT_PER_TRADE"),
        "gap_hold_pct": ("services.alert_engine", "PED_GAP_HOLD_PCT"),
        "hv_crush_pct": ("services.alert_engine", "PED_HV_CRUSH_PCT"),
        "target_pct": ("services.alert_engine", "PED_TARGET_PCT"),
        "time_stop_days": ("services.alert_engine", "PED_TIME_STOP_DAYS"),
        "cooldown_days": ("services.alert_engine", "ALERT_DEDUPE_COOLDOWN_DAYS"),
    },
}

_RULES = [
    {
        "rule_key": "alert.quality_pullback",
        "name": "Quality Pullback alert",
        "category": "setup",
        "trigger_text": (
            "Price within 2% above the 50-day or 200-day MA, 200-day MA rising, "
            "RSI(14) below 55 and was above 60 within the prior 20 sessions, "
            "volume below the 20-day average, no earnings within 5 days, "
            "SPY above its 200-day MA."
        ),
        "trigger_json": {
            "near_ma_pct": 0.02, "rsi_lt": 55, "rsi_was_above": 60,
            "rsi_exit": 68, "earnings_block_days": 5, "time_stop_days": 30,
            "risk_pct": 1.0,
        },
        "universe": "S&P 500 + Dividend Achievers + watchlist + DEFAULT_UNIVERSE",
        "action_template": "Buy {units} shares of {ticker} at ~${entry} (next open estimate).",
        "size_rule": "1% of account equity risked, sized by stop distance (entry minus 200-day MA).",
        "size_fallback": "suppress",
        "invalidation": "Close below the 200-day MA.",
        "expiry": "Signal date plus 30 days (time stop); target is the exit rule, RSI(14) above 68, no invented price target.",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "LIVE",
        "source_function": "services.alert_engine._eval_quality_pullback",
    },
    {
        "rule_key": "alert.premium_at_support",
        "name": "Premium at Support (Wheel) alert",
        "category": "setup",
        "trigger_text": (
            "Price within 2% of the 50-day MA, 200-day MA rising, IV percentile "
            "at or above 67 from the IV store only (unknown IV blocks, no HV "
            "proxy), no earnings within 5 days. Put priced from the listed "
            "chain at the bid, nearest 21 DTE, ~0.30 delta; suppressed as "
            "'no listed chain' when no listed chain is available."
        ),
        "trigger_json": {
            "near_ma_pct": 0.02, "iv_pct_min": 67,
            "target_dte": 21, "close_profit_pct": 50, "close_dte": 21,
            "earnings_block_days": 5, "time_stop_days": 30,
        },
        "universe": "S&P 500 + Dividend Achievers (same quality filter as Quality Pullback)",
        "action_template": "Sell {units} {expiry} ${strike} put(s) for ${premium} credit (listed bid).",
        "size_rule": "1% of account equity risked, sized by max loss per contract.",
        "size_fallback": "suppress",
        "invalidation": "Close below the 200-day MA; 30-day time stop.",
        "expiry": "Listed expiry nearest 21 DTE; close at 50% profit or 21 DTE.",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "SHADOW",
        "source_function": "services.alert_engine._eval_premium_at_support",
    },
    {
        "rule_key": "alert.volume_breakout",
        "name": "Volume-Confirmed Breakout alert",
        "category": "setup",
        "trigger_text": (
            "Close above the prior 55-day high, volume at least 1.5x the 20-day "
            "average, price above a rising 50-day MA, no earnings within 5 days, "
            "SPY above its 200-day MA."
        ),
        "trigger_json": {
            "prior_high_days": 55, "vol_mult": 1.5, "earnings_block_days": 5,
            "time_stop_days": 15, "atr_target_mult": 2.0, "risk_pct": 1.0,
        },
        "universe": "App directional universe (DEFAULT_UNIVERSE in stock_data.py)",
        "action_template": "Buy {units} shares of {ticker} at ~${entry} (next open estimate).",
        "size_rule": "1% of account equity risked, sized by stop distance (entry minus breakout level).",
        "size_fallback": "suppress",
        "invalidation": "Close below the breakout level (prior 55-day high).",
        "expiry": "Signal date plus 15 days (time stop); target is entry plus 2x ATR(14).",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "LIVE",
        "source_function": "services.alert_engine._eval_volume_breakout",
    },
    {
        "rule_key": "alert.directional_options",
        "name": "Directional Options alert",
        "category": "setup",
        "trigger_text": (
            "Canonical directional system: DirectionalEngine, scheduled "
            "weekdays 16:30 ET (job directional_daily). It builds one candidate "
            "per ticker from the listed 21 DTE chain, ranked by "
            "expiry-consistent EV per dollar risked. Negative payoff at target "
            "suppresses the candidate. OptionsEngine is research only and "
            "never fires an alert."
        ),
        "trigger_json": {
            "dte": 21, "premium_stop_pct": 50, "time_stop_days": 21,
        },
        "universe": "App directional universe (DEFAULT_UNIVERSE in stock_data.py)",
        "action_template": "Buy 1 {option_type} contract, {strike} exp {expiry}, at the listed premium.",
        "size_rule": "Challenge per-trade cap ($50) and max loss per contract; 1 contract only.",
        "size_fallback": "suppress",
        "invalidation": "Premium stop at -50% of entry premium, or expiry.",
        "expiry": "Option expiry (21 DTE chain).",
        "cooldown_days": 1,
        "dedupe_key_format": "directional:ticker:run-date",
        "status": "SHADOW",
        "source_function": "services.directional_engine.DirectionalEngine.run",
    },
    {
        "rule_key": "alert.champions_ai_picks",
        "name": "Champions AI Picks alert",
        "category": "setup",
        "trigger_text": (
            "Champions prescreens a universe and a written quant score "
            "(services.quant_picks.champion_score) picks 3 per run, settled "
            "on a fixed calendar horizon by strategy (30 / 21 / 90 days) on "
            "the underlying stock move. The model writes explanations only."
        ),
        "trigger_json": {
            "picks_per_run": 3, "horizons_days": [30, 21, 90],
        },
        "universe": "Champions prescreened universe",
        "action_template": "Research pick only: no trade action, graded in the Book scoreboard.",
        "size_rule": "No size: SHADOW research view, never a live trade.",
        "size_fallback": "suppress",
        "invalidation": "Fixed horizon settlement; no invalidation price.",
        "expiry": "Fixed horizon per strategy (30 / 21 / 90 days).",
        "cooldown_days": 1,
        "dedupe_key_format": "champions:ticker:run-date",
        "status": "SHADOW",
        "source_function": "services.champions_engine.run",
    },
    {
        "rule_key": "alert.directional_puts",
        "name": "Directional Puts (Down-Market) alert",
        "category": "setup",
        "trigger_text": (
            "Long puts or defined-risk bear spreads on names in a confirmed "
            "downtrend (price below a falling 50-day MA), no earnings within "
            "5 days. SHADOW ONLY: loses money on real backtests (OOS profit "
            "factor 0.69)."
        ),
        "trigger_json": {
            "earnings_block_days": 5, "time_stop_days": 21,
        },
        "universe": "App directional universe (DEFAULT_UNIVERSE in stock_data.py)",
        "action_template": "Buy 1 put contract per the listed chain, sized by max loss.",
        "size_rule": "Challenge per-trade cap ($50) and max loss per contract; 1 contract only.",
        "size_fallback": "suppress",
        "invalidation": "Defined-risk spread exits at max loss or target; long puts exit at target or on trend reversal.",
        "expiry": "21-day time stop or option expiry.",
        "cooldown_days": 1,
        "dedupe_key_format": "directional_puts:ticker:run-date",
        "status": "SHADOW",
        "source_function": "services.directional_puts.evaluate_put_candidate",
    },
    {
        "rule_key": "alert.oversold_bounce",
        "name": "Oversold Bounce alert",
        "category": "setup",
        "trigger_text": (
            "RSI(14) below 30, price above the 200-day MA, 200-day MA rising, "
            "no earnings within 5 days."
        ),
        "trigger_json": {
            "rsi_lt": 30, "rsi_exit": 50, "earnings_block_days": 5,
            "time_stop_days": 30, "risk_pct": 1.0,
        },
        "universe": "12 Step Process passing names (quality filter from the app screener)",
        "action_template": "Buy {units} shares of {ticker} at ~${entry} (next open estimate).",
        "size_rule": "1% of account equity risked, sized by stop distance (entry minus 200-day MA).",
        "size_fallback": "suppress",
        "invalidation": "Close below the 200-day MA.",
        "expiry": "Signal date plus 30 days (time stop); target is the exit rule, RSI(14) above 50, no invented price target.",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "SHADOW",
        "source_function": "services.alert_engine._eval_oversold_bounce",
    },
    {
        "rule_key": "alert.trend_pullback_reversal",
        "name": "Trend Pullback Reversal alert",
        "category": "setup",
        "trigger_text": (
            "Price above rising 20-day and 50-day MAs (today above 20 sessions "
            "ago), pullback to within 1% of the 20-day or 50-day MA, reversal "
            "confirmation: RSI(14) today above yesterday's RSI, yesterday's RSI "
            "below 50, today's RSI 40-55, OR bullish engulfing candle at the MA "
            "level, no earnings within 5 days."
        ),
        "trigger_json": {
            "near_ma_pct": 0.01, "rsi_band_low": 40, "rsi_band_high": 55,
            "rsi_prev_lt": 50,
            "atr_target_mult": 2.0, "earnings_block_days": 5,
            "time_stop_days": 15, "risk_pct": 1.0,
        },
        "universe": "App directional universe (DEFAULT_UNIVERSE in stock_data.py)",
        "action_template": "Buy {units} shares of {ticker} at ~${entry} (next open estimate).",
        "size_rule": "1% of account equity risked, sized by stop distance (entry minus signal-day low).",
        "size_fallback": "suppress",
        "invalidation": "Close below the low of the signal candle (defined risk).",
        "expiry": "Signal date plus 15 days (time stop); target is entry plus 2x ATR(14).",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "SHADOW",
        "source_function": "services.alert_engine._eval_trend_pullback_reversal",
    },
    {
        "rule_key": "alert.post_earnings_drift",
        "name": "Post-Earnings Drift alert",
        "category": "setup",
        "trigger_text": (
            "RETIRED, research only: the recipe requires an earnings beat and "
            "raised guidance, and no reliable source for either exists in "
            "this repo. The setup never fires."
        ),
        "trigger_json": {
            "gap_hold_pct": 0.005, "hv_crush_pct": 35, "target_pct": 0.10,
            "earnings_block_days": 5, "time_stop_days": 15, "risk_pct": 1.0,
        },
        "universe": "Retired: no universe, never evaluated",
        "action_template": "Research only: no trade action.",
        "size_rule": "1% of account equity risked, sized by stop distance (entry minus gap-day close).",
        "size_fallback": "suppress",
        "invalidation": "Gap fills: close below the gap-day close.",
        "expiry": "Signal date plus 15 days (time stop); target is 10% above entry, per the recipe.",
        "cooldown_days": 1,
        "dedupe_key_format": "setup:ticker:signal-date",
        "status": "RETIRED",
        "source_function": "services.alert_engine._eval_post_earnings_drift",
    },
    {
        "rule_key": "challenge.eligible_setup",
        "name": "Challenge eligible setup alert",
        "category": "challenge",
        "trigger_text": (
            "A LIVE setup alert fired within the last 48 hours, entry above "
            "stop, shares sized to the $50 per-trade cap and the max single "
            "position cap, required cash available, running open risk inside "
            "the 20% open-risk cap."
        ),
        "trigger_json": {
            "per_trade_cap_pct": 5, "per_trade_cap_dollars": 50,
            "open_risk_cap_pct": 20, "pause_drawdown_pct": 40,
            "cutoff_hours": 48,
        },
        "universe": "LIVE setup alerts from the last 48 hours",
        "action_template": "Buy {shares} shares of {ticker} at ${entry}, stop ${stop}, target ${target}.",
        "size_rule": "Per-trade cap $50 (5% of $1,000), max single position cap, open-risk cap 20%.",
        "size_fallback": "suppress",
        "invalidation": "Stop price on the alert; Challenge pause rule at 40% drawdown.",
        "expiry": "Alert ages out 48 hours after firing.",
        "cooldown_days": 0,
        "dedupe_key_format": "eligible_setup:<setup_alert_id>",
        "status": "LIVE",
        "source_function": "services.challenge_service._gen_eligible_setups",
    },
    {
        "rule_key": "challenge.eligible_directional",
        "name": "Challenge eligible directional alert",
        "category": "challenge",
        "trigger_text": (
            "A Directional candidate from the latest run with a listed entry "
            "premium and max loss inside the $50 per-trade cap. Gated on "
            "directional_options being LIVE in the setup registry; it is "
            "SHADOW, so this rule never fires a live alert."
        ),
        "trigger_json": {
            "per_trade_cap_pct": 5, "per_trade_cap_dollars": 50,
            "open_risk_cap_pct": 20, "pause_drawdown_pct": 40,
        },
        "universe": "Latest DirectionalEngine candidate batch",
        "action_template": "Buy 1 {option_type} contract, {strike} exp {expiry}, at the listed premium.",
        "size_rule": "1 contract; max loss per contract inside the $50 per-trade cap.",
        "size_fallback": "suppress",
        "invalidation": "Premium stop at -50% of entry premium, or expiry.",
        "expiry": "Option expiry.",
        "cooldown_days": 0,
        "dedupe_key_format": "eligible_directional:<candidate_id>",
        "status": "SHADOW",
        "source_function": "services.challenge_service._gen_eligible_directional",
    },
    {
        "rule_key": "challenge.position_review",
        "name": "Challenge position review alert",
        "category": "challenge",
        "trigger_text": (
            "Open position up or down 75% of planned risk, option or spread "
            "expiring within 3 days, or stock mark within 10% of target."
        ),
        "trigger_json": {
            "pnl_ratio": 0.75, "expiry_days": 3, "target_within_pct": 0.10,
        },
        "universe": "Open Challenge trades",
        "action_template": (
            "At +75% of planned risk: trail the stop to entry. "
            "At -75%: exit now at the planned max loss. "
            "Expiring within 3 days: close today, do not hold into expiry. "
            "Within 10% of target: exit at the target price when reached."
        ),
        "size_rule": "No new size: review of an existing position.",
        "size_fallback": "suppress",
        "invalidation": "Position closed or the condition no longer holds.",
        "expiry": "Same-day dedupe; re-fires daily while the condition holds.",
        "cooldown_days": 1,
        "dedupe_key_format": "position_review:<trade_id>:<condition>:<date>",
        "status": "LIVE",
        "source_function": "services.challenge_service._gen_position_reviews",
    },
    {
        "rule_key": "challenge.milestone",
        "name": "Challenge milestone alert",
        "category": "challenge",
        "trigger_text": (
            "Trading equity reaches 1.5x, 2x, 3x, 5x, or the stage target "
            "multiple of the stage starting equity."
        ),
        "trigger_json": {
            "multiples": [1.5, 2, 3, 5],
        },
        "universe": "Challenge account stage",
        "action_template": "No trade action: milestone notice only.",
        "size_rule": "No size: milestone notice only.",
        "size_fallback": "suppress",
        "invalidation": "Stage graduates; multiples are per stage.",
        "expiry": "Permanent per stage (dedupe per stage and multiple).",
        "cooldown_days": 0,
        "dedupe_key_format": "milestone:stage<id>:<multiple>x",
        "status": "LIVE",
        "source_function": "services.challenge_service._gen_milestones",
    },
    {
        "rule_key": "challenge.drawdown_warning",
        "name": "Challenge drawdown warning alert",
        "category": "challenge",
        "trigger_text": (
            "Drawdown at or past the 40% pause line, or past half the pause "
            "line (20%)."
        ),
        "trigger_json": {
            "pause_drawdown_pct": 40, "half_pause_pct": 20,
        },
        "universe": "Challenge account",
        "action_template": (
            "At the pause line: stop and review before new trades. "
            "Past half the pause line: cut per-trade risk in half, to a $25 "
            "max loss per trade, until the drawdown recovers below half the "
            "pause line."
        ),
        "size_rule": "At half pause: per-trade max loss halves to $25. At full pause: no new trades.",
        "size_fallback": "suppress",
        "invalidation": "Drawdown recovers below half the pause line.",
        "expiry": "Same-day dedupe; re-fires daily while the condition holds.",
        "cooldown_days": 1,
        "dedupe_key_format": "drawdown:stage<id>:<half|full>:<date>",
        "status": "LIVE",
        "source_function": "services.challenge_service._gen_drawdown",
    },
]


class RuleRegistryError(ValueError):
    """Raised by verify_rules when a LIVE rule is not implementable."""


def _resolve_source(source_function: str):
    """Resolve a dotted path to a callable. Returns (callable, error)."""
    try:
        module_path, attr = source_function.rsplit(".", 1)
        module = importlib.import_module(module_path)
        fn = getattr(module, attr)
        if not callable(fn):
            return None, f"{source_function} is not callable"
        return fn, None
    except Exception as e:
        return None, f"{source_function} cannot be resolved: {e}"


def seed_rule_registry(db) -> None:
    """Insert all registered rules if missing. Safe to call on startup.

    Setup rules mirror the setup registry status at seed time: a setup
    whose backtest no longer passes cannot keep a LIVE rule row. The
    setup registry is the authority on LIVE vs SHADOW; this table
    records the same verdict for the alert rule.
    """
    from models.rule_registry import RuleRegistry
    from models.setup_registry import SetupRegistry

    def _setup_status(setup_key: str, default: str) -> str:
        try:
            row = (
                db.query(SetupRegistry)
                .filter(SetupRegistry.setup_key == setup_key)
                .first()
            )
            return row.status if row is not None else default
        except Exception:
            return default

    for defn in _RULES:
        existing = (
            db.query(RuleRegistry)
            .filter(RuleRegistry.rule_key == defn["rule_key"])
            .first()
        )
        status = defn["status"]
        if defn["category"] == "setup":
            status = _setup_status(defn["rule_key"][len("alert."):], defn["status"])
        if existing:
            if existing.status != status:
                logger.info(
                    "rule_registry: syncing '%s' %s -> %s (setup registry)",
                    defn["rule_key"], existing.status, status,
                )
                existing.status = status
            # P2: sync the written rule itself, not just status, so a
            # threshold or trigger edit reaches a live DB, not only a
            # fresh one. Without this, a stale row could drift silently.
            new_trigger_json = json.dumps(defn["trigger_json"])
            if existing.trigger_text != defn["trigger_text"]:
                existing.trigger_text = defn["trigger_text"]
            if (existing.trigger_json or "") != new_trigger_json:
                existing.trigger_json = new_trigger_json
            if existing.action_template != defn["action_template"]:
                existing.action_template = defn["action_template"]
            if existing.expiry != defn["expiry"]:
                existing.expiry = defn["expiry"]
            if existing.universe != defn["universe"]:
                existing.universe = defn["universe"]
            continue
        row = RuleRegistry(
            rule_key=defn["rule_key"],
            name=defn["name"],
            category=defn["category"],
            trigger_text=defn["trigger_text"],
            trigger_json=json.dumps(defn["trigger_json"]),
            universe=defn["universe"],
            action_template=defn["action_template"],
            size_rule=defn["size_rule"],
            size_fallback=defn["size_fallback"],
            invalidation=defn["invalidation"],
            expiry=defn["expiry"],
            cooldown_days=defn["cooldown_days"],
            dedupe_key_format=defn["dedupe_key_format"],
            status=status,
            source_function=defn["source_function"],
        )
        db.add(row)
        logger.info("rule_registry: seeded '%s' as %s", defn["rule_key"], status)
    try:
        db.commit()
    except Exception as e:
        logger.error("rule_registry: seed commit failed: %s", e)
        db.rollback()


def get_rule(db, rule_key: str):
    from models.rule_registry import RuleRegistry
    return (
        db.query(RuleRegistry)
        .filter(RuleRegistry.rule_key == rule_key)
        .first()
    )


def get_all_rules(db) -> list:
    from models.rule_registry import RuleRegistry
    return db.query(RuleRegistry).order_by(RuleRegistry.id).all()


def ensure_seeded(db) -> None:
    """Seed the registry when the table is empty (first use before the
    startup seed ran, e.g. a scheduler job on a fresh database). Creates
    the table first so a database built before this phase still works."""
    from database import Base
    from models.rule_registry import RuleRegistry
    try:
        Base.metadata.create_all(db.bind, tables=[RuleRegistry.__table__])
    except Exception:
        pass
    try:
        if db.query(RuleRegistry).count() == 0:
            seed_rule_registry(db)
    except Exception as e:
        logger.warning("rule_registry: ensure_seeded failed: %s", e)


def can_fire(db, rule_key: str) -> bool:
    """True only when the rule exists in the registry and is not RETIRED.
    A rule that is not in the registry cannot fire or notify. LIVE and
    SHADOW rules can fire; SHADOW rules never create Challenge alerts or
    Telegram messages (enforced downstream by status checks)."""
    try:
        ensure_seeded(db)
        row = get_rule(db, rule_key)
    except Exception:
        return False
    if row is None:
        return False
    return row.status in ("LIVE", "SHADOW")


def verify_rules(db) -> list[str]:
    """Startup check. For every LIVE rule, verify the implementing
    function resolves and every mapped threshold in the row matches the
    constant in code. Returns the list of failures; raises
    RuleRegistryError when any LIVE rule fails, so the deploy fails
    visibly instead of firing on the wrong thresholds."""
    ensure_seeded(db)
    failures = []
    for row in get_all_rules(db):
        if row.status != "LIVE":
            continue
        _, err = _resolve_source(row.source_function)
        if err:
            failures.append(f"{row.rule_key}: {err}")
            continue
        try:
            thresholds = json.loads(row.trigger_json or "{}")
        except Exception:
            thresholds = {}
        for name, (module_path, const_name) in THRESHOLD_CHECKS.get(row.rule_key, {}).items():
            if name not in thresholds:
                continue
            try:
                module = importlib.import_module(module_path)
                live_value = getattr(module, const_name)
            except Exception as e:
                failures.append(
                    f"{row.rule_key}: threshold {name} cannot be read from "
                    f"{module_path}.{const_name}: {e}"
                )
                continue
            if live_value != thresholds[name]:
                failures.append(
                    f"{row.rule_key}: threshold {name} differs: registry "
                    f"has {thresholds[name]!r}, code has {live_value!r} "
                    f"({module_path}.{const_name})"
                )
    if failures:
        raise RuleRegistryError(
            "Rule registry startup check failed for LIVE rules: "
            + "; ".join(failures)
        )
    logger.info("rule_registry: startup check passed for %d LIVE rules",
                len([r for r in get_all_rules(db) if r.status == "LIVE"]))
    return failures
