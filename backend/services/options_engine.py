"""OptionsEngine: quant decides, Claude explains.

AI boundary (services.ai_boundary): the live path never takes a
decision field from Claude. Rank, score, grade, strategy, direction,
strike, expiry, entry, exit, and stop come from the quant scorer
and the listed option chain. Claude writes the plain-language
explanation only. A Claude failure never changes, delays, or
suppresses a pick: the pick still stores with a quant-derived
explanation.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.recommendation import Recommendation, TabType, GradeEnum
from services.ai_boundary import (
    explain_or_fallback,
    grade_from_quant_score,
    quant_fallback_explanation,
    rank_quant_candidates,
    valid_expiry_dates,
)
from services.news_scraper import NewsScraper
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
from services.quant_scorer import (
    compute_options_quant_score, compute_entry_exit_options,
    recommend_strategy_type, recommend_option_direction,
    compute_entry_exit_multi_leg,
)
import services.run_status as run_status

logger = logging.getLogger(__name__)

OPTIONS_UNIVERSE = DEFAULT_UNIVERSE[:30]
TOP_N = 5
# W9: research view only. The canonical directional system is
# DirectionalEngine. This engine never fires alerts, never notifies,
# and no longer runs on the scheduler. Manual refresh only.
RESEARCH_ONLY = True
CANONICAL_SYSTEM = "directional_engine"


def _format_news(items) -> str:
    lines = []
    for it in items[:40]:
        lines.append(f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}")
    if not lines:
        return (
            "Live news feeds are unavailable in this environment. "
            "Base recommendations on current market conditions, recent macro trends "
            "(tariff news, Fed policy, earnings season), and technical price action. "
            f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}."
        )
    return "\n".join(lines)


def _grade_to_enum(grade: str) -> GradeEnum:
    mapping = {"A": GradeEnum.A, "B": GradeEnum.B, "C": GradeEnum.C, "D": GradeEnum.D, "F": GradeEnum.F}
    return mapping.get(grade.upper(), GradeEnum.C)


def _snap_single_leg(ticker: str, option_type: str, strike: float, expiry: str) -> dict | None:
    """Snap a quant strike to the listed chain. Returns None on any failure.

    The snap is best-effort: when it succeeds the entry premium is a
    real chain price; when it fails the quant Black-Scholes estimate
    is used and labelled as an estimate in the explanation.
    """
    try:
        from services.scanner_engine import _snap_option
        return _snap_option(ticker, option_type, float(strike), expiry)
    except Exception as e:
        logger.debug("chain snap skipped for %s: %s", ticker, e)
        return None


class OptionsEngine:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = NewsScraper()
        self.stock_data = StockDataService()

    def run(self) -> None:
        logger.info("OptionsEngine: starting analysis run")
        run_status.set_running("options")
        run_at = datetime.now(timezone.utc)
        try:
            news = self.scraper.fetch_all(OPTIONS_UNIVERSE[:15])
            technicals = self.stock_data.get_technicals_bulk(OPTIONS_UNIVERSE)
            top_tickers = list(technicals.keys())[:20]
            options_data = self.stock_data.get_options_data(top_tickers)
            for t in options_data:
                if t in technicals:
                    technicals[t].update(options_data[t])

            # Quant decides: score every ticker, rank by composite, take the top 5.
            # Ties break on ticker, so the same inputs always give the same picks.
            quant_scores = {}
            for ticker, tech in technicals.items():
                if tech:
                    qs = compute_options_quant_score(tech)
                    strategy = recommend_strategy_type(tech)
                    direction = recommend_option_direction(tech)
                    ee = compute_entry_exit_options(tech, option_type=direction)
                    ml = compute_entry_exit_multi_leg(tech, strategy)
                    quant_scores[ticker] = {
                        **qs,
                        "entry_exit": ee,
                        "recommended_strategy": strategy,
                        "option_type": direction,
                        "multi_leg": ml,
                    }
            ranked = rank_quant_candidates(quant_scores)[:TOP_N]

            picks = []
            for ticker in ranked:
                qs_data = quant_scores[ticker]
                picks.append({
                    "ticker": ticker,
                    "quant_score": qs_data.get("composite"),
                    "strategy_type": qs_data.get("recommended_strategy"),
                    "option_type": qs_data.get("option_type"),
                    "underlying_entry": qs_data.get("entry_exit", {}).get("underlying_entry"),
                    "underlying_target": qs_data.get("entry_exit", {}).get("underlying_target"),
                    "underlying_stop": qs_data.get("entry_exit", {}).get("underlying_stop"),
                    "suggested_strike": qs_data.get("entry_exit", {}).get("suggested_strike"),
                })

            # Claude explains only. It receives the quant-decided picks and
            # returns text. It cannot change rank, strike, entry, or score.
            # News is context for the explanation only, never a decision input.
            explanations: dict[str, str] = {}
            if picks:
                news_str = _format_news(news)
                for pick in picks:
                    pick["news_bullets"] = news_str
                from services.claude_analyst import ClaudeAnalyst
                analyst = ClaudeAnalyst()
                explanations = explain_or_fallback(
                    analyst.explain_options, picks,
                    "Quant-decided setup; see quant score and strategy.",
                )

            self._store(picks, run_at, quant_scores, explanations)
            run_status.set_success("options")
            logger.info("OptionsEngine: stored %d recommendations", len(picks))
        except Exception as e:
            run_status.set_error("options", str(e))
            logger.error("OptionsEngine run failed: %s", e, exc_info=True)

    def _store(self, picks: list[dict], run_at: datetime,
               quant_scores: dict | None = None,
               explanations: dict | None = None) -> None:
        """Store quant-decided picks. No Claude value is read here."""
        quant_scores = quant_scores or {}
        explanations = explanations or {}
        expiry_default = valid_expiry_dates(1)[0]
        for rank, pick in enumerate(picks, start=1):
            ticker = str(pick.get("ticker", "")).upper()
            qs_data = quant_scores.get(ticker, {})
            quant_score = qs_data.get("composite")
            if quant_score is None:
                continue
            ee = qs_data.get("entry_exit", {}) or {}
            if not ee:
                logger.debug("OptionsEngine: dropping %s, no quant entry/exit", ticker)
                continue
            strategy_type = str(pick.get("strategy_type") or qs_data.get("recommended_strategy") or "single_leg")
            opt_type = str(pick.get("option_type") or "CALL").upper()
            ml = qs_data.get("multi_leg", {}) or {}

            strike = ee.get("suggested_strike")
            entry_price = ee.get("entry_premium_est")
            exit_price = ee.get("target_premium_est")
            stop_loss = ee.get("stop_premium_est")
            expiry = expiry_default
            premium_note = "Entry premium is a Black-Scholes estimate, not a live quote."
            if strategy_type == "single_leg" and strike:
                snapped = _snap_single_leg(ticker, opt_type, strike, expiry)
                if snapped and snapped.get("entry_premium"):
                    strike = snapped["strike"]
                    expiry = snapped["expiry"]
                    entry_price = snapped["entry_premium"]
                    # Quant rules on a chain price: 2x premium target, 50% stop.
                    exit_price = round(entry_price * 2.0, 2)
                    stop_loss = round(entry_price * 0.50, 2)
                    premium_note = "Entry premium from the listed chain (15-min delayed)."

            explanation = explanations.get(ticker) or quant_fallback_explanation(
                ticker, quant_score, strategy_type,
                f"Underlying entry ${ee.get('underlying_entry')}, "
                f"target ${ee.get('underlying_target')}, stop ${ee.get('underlying_stop')}.",
            )
            explanation = f"{explanation} ({premium_note})"

            obj = Recommendation(
                tab=TabType.options,
                ticker=ticker,
                rank=rank,
                score=float(quant_score),
                grade=_grade_to_enum(grade_from_quant_score(quant_score)),
                explanation=explanation,
                quant_score=round(float(quant_score), 1),
                # No Claude score in the live path: qual and combined are
                # the quant score, so nothing is blended or averaged.
                qual_score=None,
                combined_score=round(float(quant_score), 1),
                quant_components=json.dumps(qs_data.get("components", {})),
                option_type=opt_type if strategy_type == "single_leg" else "N/A",
                strategy_type=strategy_type,
                strike=strike,
                expiry=expiry,
                entry_price=entry_price,
                exit_price=exit_price,
                stop_loss=stop_loss,
                # Multi-leg strikes and payoff: quant calculator only.
                short_call_strike=ml.get("short_call_strike"),
                long_call_strike=ml.get("long_call_strike"),
                short_put_strike=ml.get("short_put_strike"),
                long_put_strike=ml.get("long_put_strike"),
                net_credit=ml.get("net_credit"),
                max_profit=ml.get("max_profit"),
                max_loss=ml.get("max_loss"),
                breakeven_low=ml.get("breakeven_low"),
                breakeven_high=ml.get("breakeven_high"),
                underlying_entry=ee.get("underlying_entry"),
                underlying_target=ee.get("underlying_target"),
                underlying_stop=ee.get("underlying_stop"),
                run_at=run_at,
            )
            self.db.add(obj)
        self.db.commit()
