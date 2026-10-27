"""WheelEngine: quant decides, Claude explains.

AI boundary (services.ai_boundary): rank, score, grade, put strike,
expiry, premium, assignment chance, and risk come from the quant
scorer and the listed option chain. Claude writes the plain-language
explanation only. A Claude failure never changes, delays, or
suppresses a pick: the pick still stores with a quant-derived
explanation. A put with no executable bid is dropped, never priced
at a last trade.
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from models.wheel import WheelRecommendation, WheelPosition, WheelStatus
from services.ai_boundary import (
    assignment_risk_from_chance,
    explain_or_fallback,
    grade_from_quant_score,
    quant_fallback_explanation,
    rank_quant_candidates,
)
from services.news_scraper import NewsScraper
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
from services.quant_scorer import compute_wheel_quant_score, compute_entry_exit_wheel
import services.run_status as run_status

logger = logging.getLogger(__name__)

WHEEL_UNIVERSE = DEFAULT_UNIVERSE
TOP_N = 5


def _format_news(items) -> str:
    lines = []
    for it in items[:40]:
        lines.append(f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}")
    if not lines:
        return (
            "Live news feeds are unavailable in this environment. "
            "Base recommendations on current market conditions, recent macro trends, "
            "and typical high-IV stocks suitable for the wheel strategy. "
            f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}."
        )
    return "\n".join(lines)


def _assignment_chance(price: float | None, strike: float | None,
                       dte: int | None, iv_pct: float | None) -> float | None:
    """Assignment chance from the Black-Scholes put delta of the listed strike.

    Delta is a quant estimate from the chain's IV, not a model guess.
    Returns None when IV is missing, so no chance is invented.
    """
    if not price or not strike or not dte or not iv_pct or iv_pct <= 0:
        return None
    try:
        from services.stock_data import _bs_put_delta
        delta = _bs_put_delta(float(price), float(strike), float(iv_pct) / 100.0,
                              max(dte, 1) / 365.0)
    except Exception:
        return None
    if delta is None:
        return None
    return round(abs(delta) * 100)


class WheelEngine:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = NewsScraper()
        self.stock_data = StockDataService()

    def run(self) -> None:
        logger.info("WheelEngine: starting analysis run")
        run_status.set_running("wheel")
        run_at = datetime.now(timezone.utc)
        try:
            news = self.scraper.fetch_all(WHEEL_UNIVERSE[:15])
            screening = self.stock_data.get_wheel_screening_data(WHEEL_UNIVERSE)
            logger.info("WheelEngine: fetched technicals for %d tickers", len(screening))

            # Quant decides: score every ticker, rank by composite, take the top 5.
            quant_scores = {}
            for ticker, tech in screening.items():
                if tech:
                    qs = compute_wheel_quant_score(tech)
                    ee = compute_entry_exit_wheel(tech)
                    quant_scores[ticker] = {**qs, "entry_exit": ee}

            ranked = rank_quant_candidates(quant_scores)[:TOP_N]

            # Snap each quant-suggested strike to the nearest real chain
            # strike. A snap with no executable bid drops the pick: a
            # put sale is priced at the bid, never at a last trade.
            picks = []
            for ticker in ranked:
                qs_data = quant_scores[ticker]
                ee = qs_data.get("entry_exit", {}) or {}
                suggested = ee.get("suggested_put_strike")
                if not suggested:
                    continue
                try:
                    snapped = self.stock_data.snap_put_strike(ticker, float(suggested))
                except Exception as snap_err:
                    logger.debug("snap_put_strike skipped for %s: %s", ticker, snap_err)
                    snapped = None
                if not snapped:
                    logger.debug("WheelEngine: dropping %s, chain snap failed", ticker)
                    continue
                sale_price = snapped.get("sale_price", 0) or 0
                if sale_price <= 0:
                    logger.debug("WheelEngine: dropping %s, no executable bid", ticker)
                    continue
                tech = screening.get(ticker, {}) or {}
                iv_pct = tech.get("atm_iv") or tech.get("iv_rank_approx")
                chance = _assignment_chance(
                    tech.get("price"), snapped["strike"], snapped.get("dte"), iv_pct
                )
                picks.append({
                    "ticker": ticker,
                    "quant_score": qs_data.get("composite"),
                    "put_strike": snapped["strike"],
                    "put_expiry": snapped["expiry"],
                    "put_premium": sale_price,
                    "premium_source": snapped.get("premium_source", "bid"),
                    "iv_rank": iv_pct,
                    "pct_otm": ee.get("pct_otm"),
                    "assignment_chance_pct": chance,
                    "assignment_risk": assignment_risk_from_chance(chance),
                    "dte": snapped.get("dte"),
                })

            # Claude explains only. News is context for the explanation,
            # never a decision input.
            explanations: dict[str, str] = {}
            if picks:
                news_str = _format_news(news)
                for pick in picks:
                    pick["news_bullets"] = news_str
                from services.claude_analyst import ClaudeAnalyst
                analyst = ClaudeAnalyst()
                explanations = explain_or_fallback(
                    analyst.explain_wheel, picks,
                    "Quant-decided wheel setup; see quant score and put strike.",
                )

            self._store(picks, run_at, quant_scores, explanations)
            run_status.set_success("wheel")
            logger.info("WheelEngine: stored %d recommendations", len(picks))
        except Exception as e:
            run_status.set_error("wheel", str(e))
            logger.error("WheelEngine run failed: %s", e, exc_info=True)

    def _store(self, picks: list[dict], run_at: datetime,
               quant_scores: dict | None = None,
               explanations: dict | None = None) -> None:
        """Store quant-decided picks. No Claude value is read here."""
        quant_scores = quant_scores or {}
        explanations = explanations or {}
        for rank, pick in enumerate(picks, start=1):
            ticker = str(pick.get("ticker", "")).upper()
            qs_data = quant_scores.get(ticker, {})
            quant_score = qs_data.get("composite")
            if quant_score is None:
                continue
            put_strike = pick.get("put_strike")
            put_premium = pick.get("put_premium")
            breakeven = round(put_strike - put_premium, 2) if put_strike and put_premium else None
            explanation = explanations.get(ticker) or quant_fallback_explanation(
                ticker, quant_score, "wheel",
                f"Put strike ${put_strike}, premium ${put_premium} at the bid, "
                f"breakeven ${breakeven}.",
            )
            obj = WheelRecommendation(
                ticker=ticker,
                rank=rank,
                score=float(quant_score),
                grade=grade_from_quant_score(quant_score),
                explanation=explanation,
                put_strike=put_strike,
                put_expiry=pick.get("put_expiry"),
                put_premium=put_premium,
                premium_source=pick.get("premium_source"),
                iv_rank=pick.get("iv_rank"),
                quant_score=round(float(quant_score), 1),
                # No Claude score in the live path: qual and combined are
                # the quant score, so nothing is blended or averaged.
                qual_score=None,
                combined_score=round(float(quant_score), 1),
                quant_components=json.dumps(qs_data.get("components", {})),
                pct_otm=pick.get("pct_otm"),
                breakeven=breakeven,
                assignment_chance_pct=pick.get("assignment_chance_pct"),
                assignment_risk=pick.get("assignment_risk"),
                run_at=run_at,
            )
            self.db.add(obj)
        self.db.commit()

    def generate_call_suggestion(self, position: WheelPosition) -> str | None:
        """Quant covered-call suggestion for an assigned position.

        Rule, written and deterministic: take the balanced call tier
        (delta 0.45) from the listed chain; if its strike is below
        cost basis, take the conservative tier (delta 0.20). The sale
        price is the bid, what the seller collects. A tier that fails
        the premium threshold or calendar check abstains, and when no
        tier qualifies there is no suggestion, never a guessed one.
        """
        try:
            current_price = self.stock_data.get_current_price(position.ticker)
            if not current_price:
                return None
            cost_basis = position.cost_basis or position.put_strike
            if not cost_basis:
                return None
            tiers = self.stock_data.get_call_tiers(position.ticker)
            if not tiers:
                return None
            from services.covered_call_service import evaluate_tier
            chosen = None
            chosen_name = None
            for name in ("balanced", "conservative"):
                tier = tiers.get(name)
                if not tier:
                    continue
                if tier.get("strike") is None or float(tier["strike"]) < float(cost_basis):
                    continue
                evaluated = evaluate_tier(tier, current_price)
                if evaluated.get("abstain"):
                    logger.debug(
                        "Call suggestion %s abstains for %s: %s",
                        name, position.ticker, evaluated.get("abstain_reasons"),
                    )
                    continue
                chosen = tier
                chosen_name = name
                break
            if not chosen:
                return None
            premium = chosen.get("sale_price") or 0
            if premium <= 0:
                return None
            rationale = (
                f"Quant rule: {chosen_name} call tier from the listed chain, "
                f"strike ${chosen['strike']} at or above cost basis ${cost_basis:.2f}, "
                f"delta {chosen.get('delta')}, bid ${premium:.2f} per share "
                f"(${premium * 100:.0f} per contract), expiry {chosen.get('expiry')} "
                f"({chosen.get('dte')} days). Premium is the bid, what the seller collects."
            )
            return json.dumps({
                "call_strike": chosen["strike"],
                "call_expiry": chosen["expiry"],
                "estimated_premium": premium,
                "premium_source": chosen.get("premium_source", "bid"),
                "delta": chosen.get("delta"),
                "call_away_chance_pct": chosen.get("call_away_chance_pct"),
                "rationale": rationale,
            })
        except Exception as e:
            logger.error("Call suggestion error for position %d: %s", position.id, e)
            return None

    def refresh_all_call_suggestions(self) -> None:
        """Weekly job: refresh call suggestions for all assigned positions."""
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        positions = (
            self.db.query(WheelPosition)
            .filter(WheelPosition.status == WheelStatus.assigned)
            .filter(
                (WheelPosition.call_suggestion_at == None) |  # noqa: E711
                (WheelPosition.call_suggestion_at < stale_cutoff)
            )
            .all()
        )
        for pos in positions:
            suggestion = self.generate_call_suggestion(pos)
            if suggestion:
                pos.call_suggestion = suggestion
                pos.call_suggestion_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info("Refreshed call suggestions for %d positions", len(positions))
