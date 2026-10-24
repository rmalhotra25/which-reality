"""
Phase 3A directional options engine.

Code ranks every candidate using transparent expectancy math; Claude writes
plain-language summaries for the top 3 only. Regime gates all new long-premium
recommendations when data is incomplete or the market is unfavorable.

Suppression rules (long-premium gate):
  data_complete=False or verdict in (UNKNOWN, RED)  -> suppress ALL new recommendations
  verdict = YELLOW                                   -> badge as against-regime (not suppressed)
  verdict = GREEN                                    -> emit normally

Every non-suppressed recommendation is journaled to SetupAlert.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.directional_candidate import DirectionalCandidate
from models.setup_alert import SetupAlert
from services.directional_ranker import (
    determine_direction,
    compute_delta,
    compute_expected_move,
    compute_payoffs,
    compute_premium_stop,
    compute_prob_profit,
    compute_prob_touch,
    compute_ranking_components,
)
from services.quant_scorer import compute_entry_exit_options
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
import services.run_status as run_status

logger = logging.getLogger(__name__)

OPTIONS_UNIVERSE = DEFAULT_UNIVERSE[:30]
DTE_TARGET = 21   # three-week expiry target for directional single-leg options
DIRECTIONAL_SETUP_KEY = "directional_options"


def _get_watchlist_tickers(db: Session) -> list[str]:
    try:
        from models.watchlist import WatchlistItem
        rows = db.query(WatchlistItem.ticker).all()
        return [r[0].upper() for r in rows if r[0]]
    except Exception:
        return []


def _get_earnings_proximity(ticker: str, dte: int) -> tuple[bool | None, int | None, bool, str | None]:
    """
    Return (earnings_in_window, days_away, earnings_unavailable, earnings_date).
    earnings_in_window: True if earnings fall within the option's DTE window.
    earnings_date is an ISO date string, or None when unknown.
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        cal = stock.calendar
        if cal is None:
            return None, None, True, None

        # yfinance returns a dict or DataFrame; normalize to dict
        if hasattr(cal, "to_dict"):
            cal = cal.to_dict()

        # Try common keys for earnings date
        earnings_dt = None
        for key in ("Earnings Date", "earningsDate"):
            val = cal.get(key)
            if val is not None:
                if isinstance(val, (list, tuple)) and len(val) > 0:
                    val = val[0]
                if hasattr(val, "date"):
                    earnings_dt = val.date()
                elif isinstance(val, str):
                    from datetime import date
                    try:
                        earnings_dt = datetime.strptime(val[:10], "%Y-%m-%d").date()
                    except Exception:
                        pass
                break

        if earnings_dt is None:
            return None, None, True, None

        today = datetime.now(timezone.utc).date()
        days_away = (earnings_dt - today).days
        in_window = 0 <= days_away <= dte
        return in_window, days_away, False, earnings_dt.isoformat()

    except Exception as e:
        logger.debug("Earnings fetch failed for %s: %s", ticker, e)
        return None, None, True, None


def earnings_suppression_reason(earnings_in_window: bool | None,
                                earnings_date: str | None,
                                earnings_days_away: int | None) -> str | None:
    """Suppression reason when earnings fall inside the expiry window, else None.

    Pure function so the earnings exclusion is unit-testable without a DB or
    a live earnings lookup. Same pattern as the wheel scanner's
    earnings_in_window exclusion.
    """
    if earnings_in_window is not True:
        return None
    when = f" on {earnings_date}" if earnings_date else ""
    days = f" ({earnings_days_away} days away)" if earnings_days_away is not None else ""
    return (
        f"earnings inside the expiry window{when}{days} - "
        "IV crush risk; excluded from the ranked list"
    )


def _get_contract_iv(ticker: str, strike: float, option_type: str, dte_target: int,
                     price: float) -> tuple[float | None, str | None]:
    """
    Implied volatility of the specific contract nearest the chosen strike at
    the expiry nearest the DTE target. Returns (iv_pct, "contract"), or
    (None, None) when no contract IV can be found, in which case the caller
    falls back to ATM IV and flags it. Polygon snapshot first (per-contract
    greeks), yfinance chain second (impliedVolatility column).
    """
    target_date = datetime.now(timezone.utc).date() + timedelta(days=dte_target)
    contract_type = option_type.lower()

    # Polygon snapshot: window the expiry range around the target so the
    # 250-contract page is not filled with sub-window weeklies.
    try:
        from services.polygon_client import get_options_chain_snapshot
        snaps = get_options_chain_snapshot(
            ticker,
            dte_min=max(0, dte_target - 7),
            dte_max=dte_target + 14,
            contract_type=contract_type,
            near_price=price,
            strike_pct_range=0.20,
        )
        best = None
        best_key = None
        for s in snaps or []:
            details = getattr(s, "details", None)
            iv = getattr(s, "implied_volatility", None)
            if not details or iv is None:
                continue
            try:
                exp = details.expiration_date
                exp_date = exp.date() if hasattr(exp, "date") else datetime.strptime(str(exp)[:10], "%Y-%m-%d").date()
                s_strike = float(details.strike_price)
                s_iv = float(iv) * 100
            except Exception:
                continue
            key = (abs((exp_date - target_date).days), abs(s_strike - strike))
            if best_key is None or key < best_key:
                best_key = key
                best = s_iv
        if best:
            return round(best, 1), "contract"
    except Exception as e:
        logger.debug("Contract IV Polygon lookup failed for %s: %s", ticker, e)

    # yfinance fallback: expiry nearest the target, then strike nearest the target.
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expiries = t.options
        if expiries:
            def _exp_date(s: str):
                return datetime.strptime(s[:10], "%Y-%m-%d").date()
            expiry = min(expiries, key=lambda s: abs((_exp_date(s) - target_date).days))
            chain = t.option_chain(expiry)
            rows = chain.calls if contract_type == "call" else chain.puts
            if rows is not None and not rows.empty and "impliedVolatility" in rows:
                row = rows.iloc[(rows["strike"] - strike).abs().argsort()[:1]]
                iv = float(row["impliedVolatility"].iloc[0]) * 100
                if iv > 0:
                    return round(iv, 1), "contract"
    except Exception as e:
        logger.debug("Contract IV yfinance lookup failed for %s: %s", ticker, e)

    return None, None


class DirectionalEngine:
    def __init__(self, db: Session):
        self.db = db
        self.stock_data = StockDataService()

    def run(self) -> None:
        logger.info("DirectionalEngine: starting analysis run")
        run_status.set_running("directional")
        run_at = datetime.now(timezone.utc)

        try:
            # 1. Regime gate
            from services.market_context import get_market_context
            ctx = get_market_context()
            verdict = ctx.get("trade_verdict", "UNKNOWN")
            data_complete = ctx.get("data_complete", False)

            suppress_all = (not data_complete) or verdict in ("UNKNOWN", "RED")
            if suppress_all:
                if not data_complete:
                    suppress_reason = (
                        "market data incomplete - underlying price or moving averages unavailable; "
                        "new long-premium recommendations suspended until data is restored"
                    )
                elif verdict == "UNKNOWN":
                    suppress_reason = (
                        "market context unknown - regime cannot be assessed; "
                        "no new long-premium positions until context is restored"
                    )
                else:
                    suppress_reason = (
                        "regime is VOLATILE (RED) - VIX elevated above 35 or market regime is volatile; "
                        "long premium buying suspended"
                    )
            else:
                suppress_reason = None

            # 2. Universe = standard universe + watchlist
            watchlist = _get_watchlist_tickers(self.db)
            universe = list(dict.fromkeys(OPTIONS_UNIVERSE + watchlist))[:40]

            # 3. Technicals
            technicals = self.stock_data.get_technicals_bulk(universe)
            options_data = self.stock_data.get_options_data(list(technicals.keys())[:20])
            for t in options_data:
                if t in technicals and technicals[t]:
                    technicals[t].update(options_data[t])

            # 4. Build candidates
            candidates: list[DirectionalCandidate] = []
            for ticker, tech in technicals.items():
                if not tech:
                    continue
                try:
                    c = self._build_candidate(ticker, tech, verdict, data_complete, run_at)
                    if c is not None:
                        candidates.append(c)
                except Exception as e:
                    logger.warning("DirectionalEngine: candidate build failed for %s: %s", ticker, e)

            # 5. Apply regime gate
            if suppress_all:
                for c in candidates:
                    c.is_suppressed = True
                    c.suppressed_reason = suppress_reason
            else:
                # Check structural suppression (max loss cannot be stated)
                for c in candidates:
                    if c.max_loss_per_contract is None or c.entry_premium is None:
                        c.is_suppressed = True
                        c.suppressed_reason = "max loss cannot be stated - entry premium unknown"
                # Earnings inside the expiry window: excluded from the ranked
                # list (same pattern as the wheel scanner's earnings handling).
                for c in candidates:
                    if c.is_suppressed:
                        continue
                    reason = earnings_suppression_reason(
                        c.earnings_in_window,
                        c.ranking_components.get("earnings_date"),
                        c.earnings_days_away,
                    )
                    if reason:
                        c.is_suppressed = True
                        c.suppressed_reason = reason

            # 6. Rank non-suppressed by score
            active = [c for c in candidates if not c.is_suppressed]
            active.sort(key=lambda c: -(c.score or 0))
            for i, c in enumerate(active):
                c.rank = i + 1

            # 7. AI explanations for top 3
            top3 = active[:3]
            if top3:
                try:
                    from services.claude_analyst import ClaudeAnalyst
                    explanations = ClaudeAnalyst().explain_directional_candidates(
                        [self._candidate_to_dict(c) for c in top3]
                    )
                    for c, exp_dict in zip(top3, explanations):
                        c.ai_explanation = exp_dict.get("explanation", "")
                        c.ai_available = True
                except Exception as e:
                    logger.warning("DirectionalEngine: AI explainer failed: %s", e)
                    for c in top3:
                        c.ai_available = False
                        c.ai_explanation = None

            # 8. Journal non-suppressed candidates
            for c in active:
                try:
                    journal_id = self._journal_candidate(c, run_at)
                    c.journal_id = journal_id
                except Exception as e:
                    logger.warning("DirectionalEngine: journal write failed for %s: %s", c.ticker, e)

            # 9. Add momentum / flow evidence (untested context labels)
            self._attach_evidence(active + [c for c in candidates if c.is_suppressed])

            # 10. Clear old candidates and store new batch
            self.db.query(DirectionalCandidate).filter(
                DirectionalCandidate.run_at < run_at
            ).delete()
            for c in candidates:
                self.db.add(c)
            self.db.commit()

            active_count = len(active)
            suppressed_count = len(candidates) - active_count
            run_status.set_success("directional")
            logger.info(
                "DirectionalEngine: stored %d active + %d suppressed candidates",
                active_count, suppressed_count,
            )

        except Exception as e:
            run_status.set_error("directional", str(e))
            logger.error("DirectionalEngine run failed: %s", e, exc_info=True)

    def _build_candidate(
        self, ticker: str, tech: dict,
        verdict: str, data_complete: bool, run_at: datetime
    ) -> DirectionalCandidate | None:
        price = tech.get("price")
        if not price or price <= 0:
            return None

        option_type = determine_direction(tech)
        ee = compute_entry_exit_options(tech, option_type)

        strike = ee.get("suggested_strike")
        entry_premium = ee.get("entry_premium_est")
        if not strike or not entry_premium:
            return None

        underlying_entry = ee.get("underlying_entry") or price
        underlying_target = ee.get("underlying_target")
        underlying_stop = ee.get("underlying_stop")

        atm_iv_pct = tech.get("atm_iv") or tech.get("iv_rank_approx") or 30.0

        # Contract IV first: the chosen contract's own implied volatility drives
        # delta, expected move, and every probability. Fall back to ATM IV only
        # when the contract IV is missing, and flag that fallback on the card.
        contract_iv_pct, iv_source = _get_contract_iv(
            ticker, strike, option_type, DTE_TARGET, price
        )
        if contract_iv_pct is None:
            iv_used = float(atm_iv_pct)
            iv_source = "atm_fallback"
        else:
            iv_used = float(contract_iv_pct)

        delta_abs = compute_delta(price, strike, DTE_TARGET, iv_used, option_type)

        # IV percentile from Phase 2A store
        from services.iv_snapshot_service import get_iv_percentile
        iv_info = get_iv_percentile(self.db, ticker)
        iv_available = iv_info.get("available", False)
        iv_percentile = iv_info.get("iv_percentile") if iv_available else None
        iv_history_building = iv_info.get("history_building", False)

        # Trend context
        ma = tech.get("moving_averages") or {}
        above_ma50 = ma.get("above_ma50")
        above_ma200 = ma.get("above_ma200")

        # Expected move (contract IV, correct 21-day horizon)
        exp_dollars, exp_pct = compute_expected_move(price, iv_used, DTE_TARGET)

        # Premium-based stop: the stock level where the option is worth 50% of
        # the entry premium, at least one expected move away from entry. This
        # replaces the old fib/ATR stock stop.
        premium_stop = compute_premium_stop(
            price, strike, entry_premium, DTE_TARGET, iv_used, option_type, exp_dollars
        )
        if premium_stop is not None:
            underlying_stop = premium_stop

        # Payoffs (stop loss is -50% of premium by the stop definition)
        payoff_target, payoff_stop, payoff_unchanged = compute_payoffs(
            option_type, strike, entry_premium, underlying_target, underlying_stop
        )

        # Real probabilities from the contract IV
        prob_profit = compute_prob_profit(
            price, strike, entry_premium, DTE_TARGET, iv_used, option_type
        )
        prob_touch_target = (
            compute_prob_touch(
                price, underlying_target, DTE_TARGET, iv_used,
                is_upper=(option_type == "CALL"),
            )
            if underlying_target else None
        )
        prob_touch_stop = (
            compute_prob_touch(
                price, underlying_stop, DTE_TARGET, iv_used,
                is_upper=(option_type == "PUT"),
            )
            if underlying_stop else None
        )

        # Ranking: real expectancy in dollars, ranked by EV per $ risked.
        components = compute_ranking_components(
            prob_profit=prob_profit,
            payoff_at_target=payoff_target,
            payoff_at_stop=payoff_stop,
            max_loss_per_contract=round(entry_premium * 100, 2),
            iv_percentile=iv_percentile,
            iv_available=iv_available,
            iv_history_building=iv_history_building,
            above_ma50=above_ma50,
            above_ma200=above_ma200,
            option_type=option_type,
        )

        # Earnings proximity
        earnings_in_window, earnings_days_away, earnings_unavailable, earnings_date = (
            _get_earnings_proximity(ticker, DTE_TARGET)
        )

        # IV crush: earnings inside the window is enough on its own. The old
        # rule also required IV in the top third, which hid the risk whenever
        # the IV percentile was still the placeholder 50.
        iv_crush_risk = earnings_in_window is True

        # Extra fields carried in the ranking-components JSON (no model schema
        # change: DirectionalCandidate has no columns for these yet).
        components["contract_iv_pct"] = contract_iv_pct
        components["iv_source"] = iv_source
        components["earnings_date"] = earnings_date
        components["prob_touch_target"] = prob_touch_target
        components["prob_touch_stop"] = prob_touch_stop
        components["delta_abs"] = round(delta_abs, 3)

        expiry_date = (
            datetime.now(timezone.utc).date() + timedelta(days=DTE_TARGET)
        ).strftime("%Y-%m-%d")

        return DirectionalCandidate(
            run_at=run_at,
            ticker=ticker,
            option_type=option_type,
            strike=round(strike, 2),
            expiry=expiry_date,
            dte=DTE_TARGET,
            entry_premium=round(entry_premium, 2),
            max_loss_per_contract=round(entry_premium * 100, 2),
            underlying_entry=round(underlying_entry, 2),
            underlying_target=round(underlying_target, 2) if underlying_target else None,
            underlying_stop=round(underlying_stop, 2) if underlying_stop else None,
            delta_abs=round(delta_abs, 3),
            current_price=round(price, 2),
            atm_iv_pct=round(atm_iv_pct, 1),
            expected_move_dollars=exp_dollars,
            expected_move_pct=exp_pct,
            payoff_at_target=payoff_target,
            payoff_at_stop=payoff_stop,
            payoff_at_unchanged=payoff_unchanged,
            iv_percentile=iv_percentile,
            iv_history_building=iv_history_building,
            iv_percentile_available=iv_available,
            above_ma50=above_ma50,
            above_ma200=above_ma200,
            earnings_in_window=earnings_in_window,
            earnings_days_away=earnings_days_away,
            earnings_unavailable=earnings_unavailable,
            iv_crush_risk=iv_crush_risk,
            regime_verdict=verdict,
            regime_data_complete=data_complete,
            score=components["score"],
            prob_score=components["prob_score"],
            rr_score=components["rr_score"],
            iv_context_score=components["iv_context_score"],
            trend_score=components["trend_score"],
            ranking_components_json=json.dumps(components),
            ai_available=None,
            ai_explanation=None,
        )

    def _candidate_to_dict(self, c: DirectionalCandidate) -> dict:
        """Minimal dict for the AI explainer prompt."""
        components = c.ranking_components
        return {
            "ticker": c.ticker,
            "rank": c.rank,
            "option_type": c.option_type,
            "strike": c.strike,
            "expiry": c.expiry,
            "entry_premium": c.entry_premium,
            "max_loss_per_contract": c.max_loss_per_contract,
            "underlying_entry": c.underlying_entry,
            "underlying_target": c.underlying_target,
            "underlying_stop": c.underlying_stop,
            "score": c.score,
            "ev_dollars": components.get("ev_dollars"),
            "ev_per_dollar_risked": components.get("ev_per_dollar_risked"),
            "prob_profit": components.get("prob_profit"),
            "prob_touch_target": components.get("prob_touch_target"),
            "prob_touch_stop": components.get("prob_touch_stop"),
            "reward_risk": components.get("reward_risk"),
            "prob_score": c.prob_score,
            "rr_score": c.rr_score,
            "iv_context_score": c.iv_context_score,
            "trend_score": c.trend_score,
            "delta_abs": c.delta_abs,
            "contract_iv_pct": components.get("contract_iv_pct"),
            "iv_source": components.get("iv_source"),
            "iv_percentile": c.iv_percentile,
            "iv_percentile_available": c.iv_percentile_available,
            "iv_history_building": c.iv_history_building,
            "iv_crush_risk": c.iv_crush_risk,
            "earnings_in_window": c.earnings_in_window,
            "earnings_date": components.get("earnings_date"),
            "earnings_days_away": c.earnings_days_away,
            "expected_move_dollars": c.expected_move_dollars,
            "expected_move_pct": c.expected_move_pct,
            "payoff_at_target": c.payoff_at_target,
            "payoff_at_stop": c.payoff_at_stop,
            "payoff_at_unchanged": c.payoff_at_unchanged,
            "above_ma50": c.above_ma50,
            "above_ma200": c.above_ma200,
            "regime_verdict": c.regime_verdict,
        }

    def _journal_candidate(self, c: DirectionalCandidate, run_at: datetime) -> int | None:
        """Write one SetupAlert row for the candidate. Returns the row id."""
        components = c.ranking_components
        snapshot = {
            "run_at": run_at.isoformat(),
            "option_type": c.option_type,
            "strike": c.strike,
            "expiry": c.expiry,
            "dte": c.dte,
            "entry_premium": c.entry_premium,
            "max_loss_per_contract": c.max_loss_per_contract,
            "underlying_entry": c.underlying_entry,
            "underlying_target": c.underlying_target,
            "underlying_stop": c.underlying_stop,
            "delta_abs": c.delta_abs,
            "score": c.score,
            "rank": c.rank,
            "ranking_components": components,
            "prob_profit": components.get("prob_profit"),
            "prob_touch_target": components.get("prob_touch_target"),
            "prob_touch_stop": components.get("prob_touch_stop"),
            "ev_dollars": components.get("ev_dollars"),
            "ev_per_dollar_risked": components.get("ev_per_dollar_risked"),
            "reward_risk": components.get("reward_risk"),
            "contract_iv_pct": components.get("contract_iv_pct"),
            "iv_source": components.get("iv_source"),
            "earnings_date": components.get("earnings_date"),
            "earnings_days_away": c.earnings_days_away,
            "expected_move_dollars": c.expected_move_dollars,
            "expected_move_pct": c.expected_move_pct,
            "payoff_at_target": c.payoff_at_target,
            "payoff_at_stop": c.payoff_at_stop,
            "payoff_at_unchanged": c.payoff_at_unchanged,
            "iv_percentile": c.iv_percentile,
            "iv_crush_risk": c.iv_crush_risk,
            "earnings_in_window": c.earnings_in_window,
            "regime_verdict": c.regime_verdict,
            "regime_data_complete": c.regime_data_complete,
            "ai_explanation": c.ai_explanation,
        }

        alert = SetupAlert(
            setup_key=DIRECTIONAL_SETUP_KEY,
            setup_name=f"Phase 3A Directional {c.option_type}",
            setup_status="SHADOW",
            ticker=c.ticker,
            fired_at=run_at,
            is_suppressed=False,
            conditions_json=json.dumps(snapshot),
            action="BUY",
            entry_price=c.underlying_entry,
            invalidation_price=c.underlying_stop,
            target_price=c.underlying_target,
            action_summary=(
                f"Buy {c.option_type} ${c.strike} exp {c.expiry} "
                f"for ${c.entry_premium:.2f} (max loss ${c.max_loss_per_contract:.0f})"
            ),
            contract_type=c.option_type,
            strike=c.strike,
            expiry=c.expiry,
            premium=c.entry_premium,
            max_loss_per_contract=c.max_loss_per_contract,
            earnings_in_window=c.earnings_in_window,
            iv_percentile=c.iv_percentile,
            invalidation_text=(
                f"Stock closes below ${c.underlying_stop:.2f}"
                if c.underlying_stop else None
            ),
            is_open=True,
        )
        self.db.add(alert)
        self.db.flush()
        return alert.id

    def _attach_evidence(self, candidates: list[DirectionalCandidate]) -> None:
        """
        Attach untested momentum and flow evidence to each candidate.
        These are displayed as context only, NOT ranking inputs.
        """
        if not candidates:
            return
        tickers = [c.ticker for c in candidates]

        # Momentum evidence (untested context - separate signal, not ranking input)
        try:
            from services.momentum_scanner_service import get_momentum_evidence
            evidence = get_momentum_evidence(tickers)
            for c in candidates:
                ev = evidence.get(c.ticker)
                if ev:
                    c.momentum_score_raw = float(ev["total_score"])
        except Exception as e:
            logger.debug("Momentum evidence attach failed: %s", e)

        # Flow evidence (untested context)
        try:
            from services.options_flow_engine import get_flow_signals_for_tickers
            flow_map = get_flow_signals_for_tickers(tickers)
            for c in candidates:
                signals = flow_map.get(c.ticker)
                if signals:
                    c.flow_signals_json = json.dumps(signals)
        except Exception as e:
            logger.debug("Flow evidence attach failed: %s", e)


def get_latest_directional_candidates(db: Session) -> list[DirectionalCandidate]:
    """Return the most recent run batch (active + suppressed, sorted by rank then ticker)."""
    from sqlalchemy import desc

    latest = (
        db.query(DirectionalCandidate.run_at)
        .order_by(desc(DirectionalCandidate.run_at))
        .first()
    )
    if not latest:
        return []

    rows = (
        db.query(DirectionalCandidate)
        .filter(DirectionalCandidate.run_at == latest[0])
        .order_by(
            DirectionalCandidate.is_suppressed,
            DirectionalCandidate.rank,
            DirectionalCandidate.ticker,
        )
        .all()
    )
    return rows
