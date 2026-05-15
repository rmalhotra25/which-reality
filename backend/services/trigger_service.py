"""
Stock Trigger Service — combines DCF/Monte Carlo, 50-day MA crossover,
earnings calendar, and bear-case protection into a 0–8 point trigger score.

Scoring:
  Monte Carlo ≥85% undervalued → +2
  Monte Carlo 70–84% undervalued → +1
  Price crossed ABOVE 50-day MA in last 5 trading days → +2
  Price above 50-day MA (no recent cross) → +1
  No earnings within 14 days → +1
  Bear case downside <30% → +1
  Base case upside >20% → +1
  ─────────────────────────────────
  Maximum: 8 points
"""
import logging

logger = logging.getLogger(__name__)


def _fetch_ma_data(ticker: str) -> dict | None:
    """
    Fetch ~100 calendar days of closes (≈70 trading days), compute 50-day SMA,
    detect whether a golden cross happened in the last 5 trading days.
    Returns None on failure or insufficient data.
    """
    try:
        from services.polygon_client import get_close_prices
        closes = get_close_prices(ticker, days=100)
        if len(closes) < 52:
            return None

        n = len(closes)
        ma50 = sum(closes[-50:]) / 50
        current_price = closes[-1]
        above_ma = current_price > ma50

        # Detect cross in last 5 trading days.
        # At index i: price=closes[i], MA=mean(closes[i-49:i+1])
        # Cross: prev_price ≤ prev_ma AND curr_price > curr_ma
        crossover_5d = False
        for i in range(max(50, n - 5), n):
            curr_p = closes[i]
            curr_m = sum(closes[i - 49:i + 1]) / 50
            prev_p = closes[i - 1]
            prev_m = sum(closes[i - 50:i]) / 50
            if prev_p <= prev_m and curr_p > curr_m:
                crossover_5d = True
                break

        return {
            "current_price": round(current_price, 2),
            "ma50": round(ma50, 2),
            "above_ma": above_ma,
            "crossover_5d": crossover_5d,
        }
    except Exception as e:
        logger.warning("MA fetch failed for %s: %s", ticker, e)
        return None


def _calculate_score(
    dcf: dict,
    ma_data: dict | None,
    earnings_days: int | None,
) -> tuple:
    """
    Returns (score, breakdown, action, suggested_size, blocked).
    breakdown keys: "monte_carlo", "ma", "earnings", "bear", "base"
    Each has: earned (int|None), max (int), label (str), detail (str), optional flags.
    """
    score = 0
    breakdown: dict = {}

    # ── 1. Monte Carlo probability (0-2 pts) ─────────────────────────────────
    mc = dcf.get("monte_carlo") or {}
    prob = mc.get("prob_undervalued_pct")
    if prob is not None:
        if prob >= 85:
            score += 2
            breakdown["monte_carlo"] = {
                "earned": 2, "max": 2, "label": "Monte Carlo",
                "detail": f"{prob}% probability undervalued",
            }
        elif prob >= 70:
            score += 1
            breakdown["monte_carlo"] = {
                "earned": 1, "max": 2, "label": "Monte Carlo",
                "detail": f"{prob}% probability undervalued (≥85% for 2 pts)",
            }
        else:
            breakdown["monte_carlo"] = {
                "earned": 0, "max": 2, "label": "Monte Carlo",
                "detail": f"{prob}% — need ≥70% to score",
            }
    else:
        breakdown["monte_carlo"] = {
            "earned": None, "max": 2, "label": "Monte Carlo",
            "detail": "No simulation data",
        }

    # ── 2. 50-day MA (0-2 pts) ───────────────────────────────────────────────
    if ma_data:
        if ma_data["crossover_5d"]:
            score += 2
            breakdown["ma"] = {
                "earned": 2, "max": 2, "label": "50-day MA",
                "detail": f"Crossed above 50-day MA in last 5 days (${ma_data['ma50']:,.2f}) — momentum signal",
                "crossover": True,
            }
        elif ma_data["above_ma"]:
            score += 1
            breakdown["ma"] = {
                "earned": 1, "max": 2, "label": "50-day MA",
                "detail": f"Price above 50-day MA (${ma_data['ma50']:,.2f})",
            }
        else:
            breakdown["ma"] = {
                "earned": 0, "max": 2, "label": "50-day MA",
                "detail": f"Price below 50-day MA (${ma_data['ma50']:,.2f})",
            }
    else:
        breakdown["ma"] = {
            "earned": None, "max": 2, "label": "50-day MA",
            "detail": "Price data unavailable",
        }

    # ── 3. No earnings within 14 days (0-1 pt) ──────────────────────────────
    has_near_earnings = earnings_days is not None and earnings_days <= 14
    if has_near_earnings:
        breakdown["earnings"] = {
            "earned": 0, "max": 1, "label": "Earnings",
            "detail": f"Earnings in {earnings_days} days — trigger blocked",
            "warning": True,
        }
    elif earnings_days is not None:
        score += 1
        breakdown["earnings"] = {
            "earned": 1, "max": 1, "label": "Earnings",
            "detail": f"Next earnings in {earnings_days} days (safe)",
        }
    else:
        score += 1
        breakdown["earnings"] = {
            "earned": 1, "max": 1, "label": "Earnings",
            "detail": "No earnings in next 30 days",
        }

    # ── 4. Bear case downside <30% (0-1 pt) ─────────────────────────────────
    bear_upside = dcf.get("dcf_bear_upside")
    if bear_upside is not None:
        bear_downside = abs(bear_upside) if bear_upside < 0 else 0
        if bear_downside < 30:
            score += 1
            breakdown["bear"] = {
                "earned": 1, "max": 1, "label": "Bear downside",
                "detail": f"Bear case {bear_upside:+.0f}% — protected downside",
                "protection": "low",
            }
        elif bear_downside <= 50:
            breakdown["bear"] = {
                "earned": 0, "max": 1, "label": "Bear downside",
                "detail": f"Bear case {bear_upside:+.0f}% — moderate risk",
                "protection": "moderate",
            }
        else:
            breakdown["bear"] = {
                "earned": 0, "max": 1, "label": "Bear downside",
                "detail": f"Bear case {bear_upside:+.0f}% — high risk, size accordingly",
                "protection": "high",
            }
    else:
        breakdown["bear"] = {
            "earned": None, "max": 1, "label": "Bear downside",
            "detail": "No DCF data",
        }

    # ── 5. Base case upside >20% (0-1 pt) ───────────────────────────────────
    base_upside = dcf.get("dcf_base_upside")
    if base_upside is not None:
        if base_upside > 20:
            score += 1
            breakdown["base"] = {
                "earned": 1, "max": 1, "label": "Base case",
                "detail": f"Base case +{base_upside:.0f}% upside",
            }
        else:
            breakdown["base"] = {
                "earned": 0, "max": 1, "label": "Base case",
                "detail": f"Base case {base_upside:+.0f}% — need >+20% for point",
            }
    else:
        breakdown["base"] = {
            "earned": None, "max": 1, "label": "Base case",
            "detail": "No DCF data",
        }

    # ── Action & position sizing ─────────────────────────────────────────────
    blocked = has_near_earnings
    if blocked:
        action, suggested_size = "BLOCKED", None
    elif score >= 7:
        action, suggested_size = "STRONG BUY", "$75–100/week"
    elif score >= 5:
        action, suggested_size = "SMALL BUY", "$25–50/week"
    elif score >= 3:
        action, suggested_size = "WATCH", None
    else:
        action, suggested_size = "PASS", None

    return score, breakdown, action, suggested_size, blocked


def analyze_trigger(ticker: str) -> dict:
    """
    Full trigger analysis: DCF + Monte Carlo + 50-day MA + earnings → trigger score.
    Raises ValueError if fundamentals are unavailable (propagated from dcf_service).
    """
    from services.dcf_service import analyze as dcf_analyze
    from services.finnhub_client import get_earnings_this_month

    ticker = ticker.upper().strip()

    dcf = dcf_analyze(ticker)

    ma_data = _fetch_ma_data(ticker)
    try:
        earnings_days = get_earnings_this_month(ticker)
    except Exception:
        earnings_days = None

    score, breakdown, action, suggested_size, blocked = _calculate_score(
        dcf, ma_data, earnings_days
    )

    bear_upside = dcf.get("dcf_bear_upside")
    if bear_upside is not None:
        bear_downside = abs(bear_upside) if bear_upside < 0 else 0
        if bear_downside < 30:
            bear_protection_label = "Protected downside"
            bear_protection_level = "low"
        elif bear_downside <= 50:
            bear_protection_label = "Moderate downside risk"
            bear_protection_level = "moderate"
        else:
            bear_protection_label = "High downside risk — position size accordingly"
            bear_protection_level = "high"
    else:
        bear_protection_label = None
        bear_protection_level = None

    return {
        **dcf,
        "trigger_score": score,
        "trigger_action": action,
        "trigger_blocked": blocked,
        "suggested_position_size": suggested_size,
        "trigger_breakdown": breakdown,
        "ma50": ma_data["ma50"] if ma_data else None,
        "above_ma": ma_data["above_ma"] if ma_data else None,
        "crossover_5d": ma_data["crossover_5d"] if ma_data else None,
        "earnings_days": earnings_days,
        "bear_protection_label": bear_protection_label,
        "bear_protection_level": bear_protection_level,
    }
