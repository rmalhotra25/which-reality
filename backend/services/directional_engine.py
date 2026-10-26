"""
Phase 3A directional options engine.

Code ranks every candidate using transparent expectancy math; Claude writes
plain-language summaries for the top 3 only. Regime gates all new long-premium
recommendations when data is incomplete or the market is unfavorable.

Suppression rules (long-premium gate):
  data_complete=False or verdict in (UNKNOWN) -> suppress ALL new recommendations
  verdict = RED                               -> suppress CALLs; PUTs are allowed,
                                                 flagged as caution, as a hedge or
                                                 speculation only
  verdict = YELLOW                            -> badge as against-regime (not suppressed);
                                                 in a BEAR regime puts are favoured
  verdict = GREEN                             -> emit normally

Pricing: the premium is priced at the stated 21 DTE from the real
listed chain, never from the 7-day Black-Scholes estimate. Expiry is
snapped to the nearest listed expiry at or after 21 DTE and the strike
to the nearest listed strike. A bought option is filled at the ask
when buying; on this data plan bid/ask are 0.0, so when the ask is
absent the premium falls back to the last trade, then fair value, and
the premium source is always recorded on the candidate. When no chain
is available the candidate is suppressed, never priced from an estimate.
When payoff at target is negative (the target sits below breakeven, so
hitting the target still loses money) the candidate is suppressed too.
Payoff at stop is always negative by design and is never a suppression
reason on its own.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

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
from services.directional_puts import (
    bear_spread_payoff_at_target,
    bear_spread_payoffs,
    choose_bear_spread_short_leg,
    evaluate_put_candidate,
    put_plain_copy,
)
import services.run_status as run_status

logger = logging.getLogger(__name__)


def invalidation_text(option_type: str, stop: float | None) -> str | None:
    """Invalidation line for a candidate. A PUT stop sits above the
    entry, so a put fails when the stock closes ABOVE the stop; a CALL
    fails when the stock closes BELOW the stop."""
    if stop is None:
        return None
    if (option_type or "").upper() == "PUT":
        return f"Stock closes above ${stop:.2f}"
    return f"Stock closes below ${stop:.2f}"


def _parse_expiry(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def snap_expiry_to_listed(expiries, target_date: date) -> date | None:
    """Nearest listed expiry at or after the target date, or None.

    A calendar date 21 days out may be a Saturday, Sunday, or holiday
    with no listed expiry; this snaps forward to a real expiry.
    """
    parsed = [d for d in (_parse_expiry(e) for e in (expiries or [])) if d is not None]
    at_or_after = [d for d in parsed if d >= target_date]
    if not at_or_after:
        return None
    return min(at_or_after)


def snap_strike_to_listed(strikes, target_strike: float) -> float | None:
    """Nearest listed strike to the target strike, or None."""
    values = [float(s) for s in (strikes or []) if s is not None]
    if not values or target_strike is None:
        return None
    return min(values, key=lambda s: abs(s - target_strike))


def premium_from_quote(bid, ask, last_trade, fair_value) -> tuple[float | None, str | None]:
    """Fill price for a BOUGHT option: the ask when buying.

    Prefer the listed ask. On this data plan bid/ask are 0.0, so fall
    back to the last trade, then fair value. Returns (premium, source)
    where source is "ask", "last trade", or "fair value". A last-trade
    or fair-value premium is never presented as a live quote.
    """
    for value, source in (
        (ask, "ask"),
        (last_trade, "last trade"),
        (fair_value, "fair value"),
    ):
        try:
            if value is not None and float(value) > 0:
                return round(float(value), 2), source
        except Exception:
            continue
    return None, None


def premium_for_sale(bid, last_trade, fair_value) -> tuple[float | None, str | None]:
    """Fill price for a SOLD option leg: the bid when selling, with the
    same last-trade then fair-value fallback as a buy."""
    for value, source in (
        (bid, "bid"),
        (last_trade, "last trade"),
        (fair_value, "fair value"),
    ):
        try:
            if value is not None and float(value) > 0:
                return round(float(value), 2), source
        except Exception:
            continue
    return None, None


def select_listed_contract(contracts: list, target_date: date,
                           target_strike: float,
                           as_of_date: date | None = None) -> dict | None:
    """Pick the listed contract nearest the target expiry and strike.

    Contracts are dicts with expiry (date or "YYYY-MM-DD"), strike,
    bid, ask, last_trade, fair_value, iv_pct. Expiry must be at or
    after the target date; the strike is the nearest listed strike at
    that expiry. Returns None when no listed expiry at or after the
    target exists. The premium is priced from the listed contract at
    the stated DTE, never from a 7-day estimate.
    """
    if not contracts:
        return None
    today = as_of_date or date.today()
    expiries = [c.get("expiry") for c in contracts]
    expiry = snap_expiry_to_listed(expiries, target_date)
    if expiry is None:
        return None
    at_expiry = [c for c in contracts if _parse_expiry(c.get("expiry")) == expiry]
    if not at_expiry:
        return None
    strike = snap_strike_to_listed([c.get("strike") for c in at_expiry], target_strike)
    if strike is None:
        return None
    row = min(at_expiry, key=lambda c: abs(float(c.get("strike") or 0) - strike))
    premium, source = premium_from_quote(
        row.get("bid"), row.get("ask"), row.get("last_trade"), row.get("fair_value")
    )
    iv_pct = row.get("iv_pct")
    return {
        "expiry": expiry,
        "expiry_str": expiry.isoformat(),
        "strike": float(row.get("strike")),
        "dte": (expiry - today).days,
        "premium": premium,
        "premium_source": source,
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "iv_pct": float(iv_pct) if iv_pct is not None else None,
    }


def _has_tradable_premium(rows: list) -> bool:
    """True when at least one row has a premium to price from.

    On the Massive Options Starter plan bid/ask are 0.0, so a row is
    tradable when its ask, last trade, or fair value is above zero.
    A chain of rows with none of those is not a usable chain, even
    though rows were returned: Polygon can return a full snapshot
    page for the 21 to 35 DTE window whose contracts have not traded
    yet that day, so last_trade and fair_value are both empty.
    """
    for row in rows or []:
        for field in ("ask", "last_trade", "fair_value"):
            try:
                if row.get(field) is not None and float(row.get(field)) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _fetch_yfinance_chain(ticker: str, option_type: str,
                          target_date: date) -> list:
    """Nearest listed expiry at or after the target, via yfinance.

    Returns contract dicts in the same shape as the Polygon rows, with
    lastPrice as last_trade. Returns an empty list when no expiry at
    or after the target exists or the lookup fails. Never invents a
    premium: a contract with no lastPrice, bid, or ask has no premium.
    """
    contract_type = option_type.lower()
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expiries = t.options or []
        expiry = snap_expiry_to_listed(expiries, target_date)
        if expiry is None:
            return []
        chain = t.option_chain(expiry.isoformat())
        df = chain.calls if contract_type == "call" else chain.puts
        rows = []
        for _, r in df.iterrows():
            try:
                strike = float(r.get("strike") or 0)
            except Exception:
                continue
            if strike <= 0:
                continue
            iv = r.get("impliedVolatility")
            rows.append({
                "expiry": expiry,
                "strike": strike,
                "bid": float(r.get("bid") or 0) or None,
                "ask": float(r.get("ask") or 0) or None,
                "last_trade": float(r.get("lastPrice") or 0) or None,
                "fair_value": None,
                "iv_pct": round(float(iv) * 100, 1) if iv else None,
            })
        return rows
    except Exception as e:
        logger.debug("Listed chain yfinance lookup failed for %s: %s", ticker, e)
        return []


def _yfinance_contract(ticker: str, option_type: str, target_date: date,
                       strike_target: float) -> dict | None:
    """One listed contract via yfinance, for a Polygon contract with no premium.

    Picks the same snapped expiry and nearest strike as
    select_listed_contract, but prices from yfinance and labels the
    source so the card can flag it (for example "yfinance last trade"
    or "yfinance ask"). Returns None when yfinance has no tradable
    premium for that contract either.
    """
    rows = _fetch_yfinance_chain(ticker, option_type, target_date)
    if not rows:
        return None
    picked = select_listed_contract(rows, target_date, strike_target,
                                    as_of_date=date.today())
    if picked is None or picked.get("premium") is None:
        return None
    raw_source = picked.get("premium_source")
    picked["premium_source"] = f"yfinance {raw_source}" if raw_source else "yfinance"
    return picked


def fetch_listed_chain(ticker: str, option_type: str, price: float) -> list:
    """Listed options chain for expiries at or after the 21 DTE target.

    Polygon snapshot first (windowed at the target so the 250-contract
    page is not filled with sub-window weeklies), yfinance second for
    the nearest listed expiry at or after the target. Returns a list
    of contract dicts (possibly empty when no chain is available).

    The yfinance fallback runs not only when Polygon returns no rows
    but also when Polygon returns rows with no tradable premium at
    all. Before this fix, a full Polygon page with empty premiums
    short-circuited the fallback, so every candidate was suppressed
    even though the contracts were tradable on yfinance (Oct 26, 2026:
    AAPL Nov 20 $350 call, lastPrice $9.70 on yfinance, no premium in
    the Polygon snapshot).
    """
    target_date = date.today() + timedelta(days=DTE_TARGET)
    contract_type = option_type.lower()

    try:
        from services.polygon_client import get_options_chain_snapshot
        snaps = get_options_chain_snapshot(
            ticker,
            dte_min=DTE_TARGET,
            dte_max=DTE_TARGET + 14,
            contract_type=contract_type,
            near_price=price,
            strike_pct_range=0.20,
        )
        rows = []
        for s in snaps or []:
            details = getattr(s, "details", None)
            if not details:
                continue
            try:
                expiry = _parse_expiry(details.expiration_date)
                strike = float(details.strike_price)
            except Exception:
                continue
            if expiry is None or strike <= 0:
                continue
            bid = ask = last = fair = None
            if getattr(s, "last_quote", None):
                bid = float(s.last_quote.bid or 0) or None
                ask = float(s.last_quote.ask or 0) or None
            if getattr(s, "last_trade", None) and s.last_trade.price:
                last = float(s.last_trade.price)
            if getattr(s, "fair_market_value", None):
                fair = float(s.fair_market_value)
            iv = getattr(s, "implied_volatility", None)
            rows.append({
                "expiry": expiry,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "last_trade": last,
                "fair_value": fair,
                "iv_pct": round(float(iv) * 100, 1) if iv else None,
            })
        if rows and _has_tradable_premium(rows):
            return rows
        if rows:
            logger.debug(
                "Listed chain Polygon rows for %s have no tradable premium, "
                "falling back to yfinance", ticker)
    except Exception as e:
        logger.debug("Listed chain Polygon lookup failed for %s: %s", ticker, e)

    return _fetch_yfinance_chain(ticker, option_type, target_date)


def resolve_listed_contract(ticker: str, strike_target: float,
                            option_type: str, price: float,
                            chain: list | None = None) -> dict | None:
    """Listed contract at the stated 21 DTE, or None when no chain exists.

    If the Polygon contract at the snapped expiry and strike has no
    tradable premium, one yfinance lookup is tried for that same
    contract before giving up. If yfinance also has no premium, None
    is returned in effect (a dict with premium None), and the caller
    still suppresses the candidate with the same reason as before.
    No premium is ever invented or model-priced.
    """
    if chain is None:
        chain = fetch_listed_chain(ticker, option_type, price)
    target_date = date.today() + timedelta(days=DTE_TARGET)
    picked = select_listed_contract(chain, target_date, strike_target, as_of_date=date.today())
    if picked is None:
        return None
    if picked.get("premium") is not None:
        return picked
    return _yfinance_contract(ticker, option_type, target_date, strike_target) or picked

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


def negative_payoff_suppression_reason(payoff_at_target: float | None) -> str | None:
    """Suppression reason when payoff at target is negative, else None.

    Rule: suppress when payoff_at_target < 0. A payoff of exactly zero
    (target equals breakeven) is not suppressed by this rule. Payoff at
    target is the existing compute_payoffs figure: intrinsic value at
    the target stock price minus premium paid, per contract. For a CALL
    that is max(0, target - strike) - premium, times 100; for a PUT it
    is max(0, strike - target) - premium, times 100. A negative payoff
    means hitting the target still loses money, because the target sits
    below breakeven, so the candidate is not a tradeable idea.

    Pure function so the exclusion is unit-testable without a DB or a
    live chain lookup, same pattern as earnings_suppression_reason.
    Payoff at stop is deliberately not checked here: the stop loss is
    negative by design, at -50% of premium.
    """
    if payoff_at_target is None or payoff_at_target >= 0:
        return None
    return (
        f"payoff at target is negative (${payoff_at_target:.0f} per contract, "
        "target below breakeven) - candidate suppressed"
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
            # 1. Regime gate (direction-aware: RED suppresses calls only,
            # puts are allowed, flagged as caution; see market_context)
            from services.market_context import get_market_context
            ctx = get_market_context()
            verdict = ctx.get("trade_verdict", "UNKNOWN")
            regime = ctx.get("market_regime", "UNKNOWN")
            data_complete = ctx.get("data_complete", False)

            suppress_all = (not data_complete) or verdict == "UNKNOWN"
            red_suppresses_calls = verdict == "RED"
            if suppress_all:
                if not data_complete:
                    suppress_reason = (
                        "market data incomplete - underlying price or moving averages unavailable; "
                        "new long-premium recommendations suspended until data is restored"
                    )
                else:
                    suppress_reason = (
                        "market context unknown - regime cannot be assessed; "
                        "no new long-premium positions until context is restored"
                    )
            elif red_suppresses_calls:
                suppress_reason = (
                    "regime is VOLATILE (RED) - VIX elevated above 35 or market regime is volatile; "
                    "long calls suspended, puts allowed only as a hedge or speculation"
                )
            else:
                suppress_reason = None

            # 2. Universe = standard universe + watchlist
            watchlist = _get_watchlist_tickers(self.db)
            universe = list(dict.fromkeys(OPTIONS_UNIVERSE + watchlist))[:40]

            # 3. Technicals
            technicals = self.stock_data.get_technicals_bulk(universe)
            # Options data for the FULL universe, not just the first 20:
            # watchlist tickers were previously priced at a hardcoded 30%
            # IV because they never received live IV.
            options_data = self.stock_data.get_options_data(list(technicals.keys()))
            for t in options_data:
                if t in technicals and technicals[t]:
                    technicals[t].update(options_data[t])

            # 4. Build candidates
            candidates: list[DirectionalCandidate] = []
            for ticker, tech in technicals.items():
                if not tech:
                    continue
                try:
                    c = self._build_candidate(ticker, tech, verdict, data_complete, run_at, regime=regime)
                    if c is not None:
                        candidates.append(c)
                except Exception as e:
                    logger.warning("DirectionalEngine: candidate build failed for %s: %s", ticker, e)

            # 5. Apply regime gate
            if suppress_all:
                for c in candidates:
                    if not c.is_suppressed:
                        c.is_suppressed = True
                        c.suppressed_reason = suppress_reason
            elif red_suppresses_calls:
                for c in candidates:
                    if c.is_suppressed:
                        continue
                    if c.option_type == "CALL":
                        c.is_suppressed = True
                        c.suppressed_reason = suppress_reason
                    else:
                        # Puts are allowed in RED, flagged as caution.
                        comps = c.ranking_components
                        comps["red_regime_put_allowed"] = True
                        comps["put_regime_note"] = (
                            "RED regime: puts allowed only as a hedge or speculation, "
                            "calls are suppressed"
                        )
                        c.ranking_components = comps
            if not suppress_all:
                # Check structural suppression (max loss cannot be stated)
                for c in candidates:
                    if c.is_suppressed:
                        continue
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
                # Payoff at target negative: excluded from the ranked list.
                # Belt and braces for the _build_candidate check above, in
                # case a payoff is repriced after build (bear spread).
                for c in candidates:
                    if c.is_suppressed:
                        continue
                    reason = negative_payoff_suppression_reason(c.payoff_at_target)
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

    def _suppressed_candidate(self, ticker: str, tech: dict, option_type: str,
                              verdict: str, data_complete: bool, run_at: datetime,
                              reason: str, ee: dict | None = None,
                              strike_target=None) -> DirectionalCandidate:
        """A candidate row that is suppressed, kept visible so the UI can
        show why it did not qualify instead of silently dropping it."""
        price = tech.get("price")
        return DirectionalCandidate(
            run_at=run_at,
            ticker=ticker,
            option_type=option_type,
            strike=round(strike_target, 2) if strike_target else None,
            expiry=None,
            dte=DTE_TARGET,
            entry_premium=None,
            max_loss_per_contract=None,
            underlying_entry=round(price, 2) if price else None,
            underlying_target=round(ee.get("underlying_target"), 2) if ee and ee.get("underlying_target") else None,
            underlying_stop=round(ee.get("underlying_stop"), 2) if ee and ee.get("underlying_stop") else None,
            delta_abs=None,
            current_price=round(price, 2) if price else None,
            atm_iv_pct=tech.get("atm_iv"),
            expected_move_dollars=None,
            expected_move_pct=None,
            payoff_at_target=None,
            payoff_at_stop=None,
            payoff_at_unchanged=None,
            iv_percentile=None,
            iv_history_building=False,
            iv_percentile_available=False,
            above_ma50=(tech.get("moving_averages") or {}).get("above_ma50"),
            above_ma200=(tech.get("moving_averages") or {}).get("above_ma200"),
            earnings_in_window=None,
            earnings_days_away=None,
            earnings_unavailable=None,
            iv_crush_risk=False,
            regime_verdict=verdict,
            regime_data_complete=data_complete,
            score=None,
            prob_score=None,
            rr_score=None,
            iv_context_score=None,
            trend_score=None,
            ranking_components_json=json.dumps({"suppression_reason": reason}),
            is_suppressed=True,
            suppressed_reason=reason,
            ai_available=None,
            ai_explanation=None,
        )

    def _build_candidate(
        self, ticker: str, tech: dict,
        verdict: str, data_complete: bool, run_at: datetime,
        regime: str = "UNKNOWN",
    ) -> DirectionalCandidate | None:
        price = tech.get("price")
        if not price or price <= 0:
            return None

        option_type = determine_direction(tech)
        # compute_entry_exit_options still supplies the stock target, stop,
        # and suggested strike, but its 7-day BS entry premium is NEVER
        # used as the price: the premium comes from the listed chain below.
        ee = compute_entry_exit_options(tech, option_type)
        strike_target = ee.get("suggested_strike")
        if not strike_target:
            return None
        underlying_entry = ee.get("underlying_entry") or price
        underlying_target = ee.get("underlying_target")
        underlying_stop = ee.get("underlying_stop")

        # Listed chain at the stated 21 DTE: expiry snapped to the nearest
        # listed expiry at or after 21 days, strike snapped to the nearest
        # listed strike, premium from that listed contract.
        chain = fetch_listed_chain(ticker, option_type, price)
        listed = resolve_listed_contract(ticker, strike_target, option_type, price, chain=chain)
        if listed is None:
            return self._suppressed_candidate(
                ticker, tech, option_type, verdict, data_complete, run_at,
                "no listed options chain at or after 21 days to expiry - "
                "candidate suppressed, the 7-day estimated premium is not used",
                ee=ee, strike_target=strike_target,
            )
        if listed.get("premium") is None:
            return self._suppressed_candidate(
                ticker, tech, option_type, verdict, data_complete, run_at,
                "listed contract at 21 days to expiry has no tradable premium "
                "(no ask, no last trade, no fair value) - candidate suppressed",
                ee=ee, strike_target=strike_target,
            )

        strike = listed["strike"]
        expiry_date = listed["expiry_str"]
        dte_actual = listed["dte"]
        entry_premium = listed["premium"]
        premium_source = listed["premium_source"]

        # Contract IV first: the listed contract's own IV when present,
        # then the nearest-contract lookup, then ATM IV flagged as a
        # fallback. No hardcoded 30% IV: without any live IV the
        # candidate is suppressed as unknown-IV.
        contract_iv_pct = listed.get("iv_pct")
        iv_source = "contract" if contract_iv_pct else None
        if contract_iv_pct is None:
            contract_iv_pct, iv_source = _get_contract_iv(
                ticker, strike, option_type, dte_actual, price
            )
        atm_iv_pct = tech.get("atm_iv") or tech.get("iv_rank_approx")
        if contract_iv_pct is None:
            if atm_iv_pct:
                iv_used = float(atm_iv_pct)
                iv_source = "atm_fallback"
            else:
                return self._suppressed_candidate(
                    ticker, tech, option_type, verdict, data_complete, run_at,
                    "no live IV for the listed contract or the underlying - "
                    "candidate suppressed as unknown-IV, never priced at 30%",
                    ee=ee, strike_target=strike_target,
                )
        else:
            iv_used = float(contract_iv_pct)

        delta_abs = compute_delta(price, strike, dte_actual, iv_used, option_type)

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

        # Expected move (contract IV, actual listed DTE)
        exp_dollars, exp_pct = compute_expected_move(price, iv_used, dte_actual)

        # Premium-based stop: the stock level where the option is worth 50% of
        # the entry premium, at least one expected move away from entry.
        premium_stop = compute_premium_stop(
            price, strike, entry_premium, dte_actual, iv_used, option_type, exp_dollars
        )
        if premium_stop is not None:
            underlying_stop = premium_stop

        # Payoffs (stop loss is -50% of premium by the stop definition)
        payoff_target, payoff_stop, payoff_unchanged = compute_payoffs(
            option_type, strike, entry_premium, underlying_target, underlying_stop
        )

        # A candidate whose payoff at target is negative loses money even
        # when the stock hits its target, because the target sits below
        # breakeven. It is not a tradeable idea, so suppress it here
        # instead of ranking it. Payoff at stop is not checked: the stop
        # loss is negative by design.
        payoff_reason = negative_payoff_suppression_reason(payoff_target)
        if payoff_reason:
            return self._suppressed_candidate(
                ticker, tech, option_type, verdict, data_complete, run_at,
                payoff_reason,
                ee=ee, strike_target=strike_target,
            )

        # Real probabilities from the contract IV
        prob_profit = compute_prob_profit(
            price, strike, entry_premium, dte_actual, iv_used, option_type
        )
        prob_touch_target = (
            compute_prob_touch(
                price, underlying_target, dte_actual, iv_used,
                is_upper=(option_type == "CALL"),
            )
            if underlying_target else None
        )
        prob_touch_stop = (
            compute_prob_touch(
                price, underlying_stop, dte_actual, iv_used,
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

        # Earnings proximity (actual listed DTE window)
        earnings_in_window, earnings_days_away, earnings_unavailable, earnings_date = (
            _get_earnings_proximity(ticker, dte_actual)
        )

        # IV crush: earnings inside the window is enough on its own.
        iv_crush_risk = earnings_in_window is True

        # Extra fields carried in the ranking-components JSON (no model schema
        # change: DirectionalCandidate has no columns for these yet).
        components["contract_iv_pct"] = contract_iv_pct
        components["iv_source"] = iv_source
        components["earnings_date"] = earnings_date
        components["prob_touch_target"] = prob_touch_target
        components["prob_touch_stop"] = prob_touch_stop
        components["delta_abs"] = round(delta_abs, 3)
        components["premium_source"] = premium_source
        components["listed_expiry"] = expiry_date
        components["listed_strike"] = strike
        components["dte_actual"] = dte_actual
        components["invalidation_text"] = invalidation_text(option_type, underlying_stop)

        # Direction-aware regime flag for the card.
        from services.market_context import verdict_for_direction
        dir_verdict = verdict_for_direction(verdict, regime, option_type)
        components["direction_verdict"] = dir_verdict
        components["regime_favours_put"] = bool(
            option_type == "PUT" and dir_verdict == "GREEN"
        )

        # Put strategy rules (directional_puts.py): trend, delta band,
        # IV discipline (rich IV routes to the bear spread), EV above zero.
        put_variant = None
        spread = None
        if option_type == "PUT":
            put_eval = evaluate_put_candidate(
                prob_profit, payoff_target, payoff_stop,
                round(entry_premium * 100, 2),
                iv_percentile, iv_available, above_ma50, above_ma200,
                earnings_in_window, delta_abs,
            )
            if put_eval["decision"] == "excluded":
                return self._suppressed_candidate(
                    ticker, tech, option_type, verdict, data_complete, run_at,
                    "put strategy: " + "; ".join(put_eval["reasons"]),
                    ee=ee, strike_target=strike_target,
                )
            if put_eval["decision"] == "spread":
                short_leg = choose_bear_spread_short_leg(chain, expiry_date, strike, price)
                if short_leg is None:
                    return self._suppressed_candidate(
                        ticker, tech, option_type, verdict, data_complete, run_at,
                        "put strategy: IV is rich so only a bear spread is allowed, "
                        "but no listed short leg was found at the same expiry",
                        ee=ee, strike_target=strike_target,
                    )
                short_premium, short_source = premium_for_sale(
                    short_leg.get("bid"), short_leg.get("last_trade"), short_leg.get("fair_value")
                )
                if short_premium is None or short_premium >= entry_premium:
                    return self._suppressed_candidate(
                        ticker, tech, option_type, verdict, data_complete, run_at,
                        "put strategy: bear spread short leg has no tradable premium "
                        "or costs at least as much as the long leg",
                        ee=ee, strike_target=strike_target,
                    )
                spread = bear_spread_payoffs(strike, float(short_leg["strike"]), entry_premium, short_premium)
                spread["long_strike"] = strike
                spread["short_strike"] = float(short_leg["strike"])
                spread["short_premium"] = short_premium
                spread["short_premium_source"] = short_source
                net_debit = spread["net_debit"]
                # Re-price the candidate as the spread: capped loss is the
                # net debit, payoff at target is the spread payoff, and
                # P(profit) is P(stock finishes below the spread breakeven).
                entry_premium = net_debit
                payoff_target = bear_spread_payoff_at_target(
                    strike, float(short_leg["strike"]), net_debit, underlying_target
                ) if underlying_target else None
                payoff_stop = round(-net_debit * 100 * 0.50, 0)
                payoff_unchanged = round(-net_debit * 100, 0)
                # Same negative-payoff rule on the repriced spread payoff.
                spread_payoff_reason = negative_payoff_suppression_reason(payoff_target)
                if spread_payoff_reason:
                    return self._suppressed_candidate(
                        ticker, tech, option_type, verdict, data_complete, run_at,
                        spread_payoff_reason,
                        ee=ee, strike_target=strike_target,
                    )
                prob_profit = compute_prob_profit(
                    price, strike, net_debit, dte_actual, iv_used, option_type
                )
                components = compute_ranking_components(
                    prob_profit=prob_profit,
                    payoff_at_target=payoff_target,
                    payoff_at_stop=payoff_stop,
                    max_loss_per_contract=round(net_debit * 100, 2),
                    iv_percentile=iv_percentile,
                    iv_available=iv_available,
                    iv_history_building=iv_history_building,
                    above_ma50=above_ma50,
                    above_ma200=above_ma200,
                    option_type=option_type,
                )
                components["contract_iv_pct"] = contract_iv_pct
                components["iv_source"] = iv_source
                components["earnings_date"] = earnings_date
                components["prob_touch_target"] = prob_touch_target
                components["prob_touch_stop"] = prob_touch_stop
                components["delta_abs"] = round(delta_abs, 3)
                components["premium_source"] = premium_source
                components["listed_expiry"] = expiry_date
                components["listed_strike"] = strike
                components["dte_actual"] = dte_actual
                components["invalidation_text"] = invalidation_text(option_type, underlying_stop)
                components["direction_verdict"] = dir_verdict
                components["regime_favours_put"] = bool(dir_verdict == "GREEN")
                # Negative EV on the spread itself still excludes it.
                if components.get("ev_dollars") is not None and components["ev_dollars"] <= 0:
                    return self._suppressed_candidate(
                        ticker, tech, option_type, verdict, data_complete, run_at,
                        f"put strategy: bear spread expected value "
                        f"${components['ev_dollars']:.0f} per contract is not above zero, excluded",
                        ee=ee, strike_target=strike_target,
                    )
                put_variant = "bear_spread"
                components["put_variant"] = "bear_spread"
                components["spread"] = spread
                components["spread_breakeven"] = spread["breakeven"]
            else:
                put_variant = "outright"
                components["put_variant"] = "outright"
            components["put_iv_route"] = put_eval["reasons"][0] if put_eval.get("reasons") else None
            components["put_plain_copy"] = put_plain_copy(
                ticker, strike, expiry_date, entry_premium,
                round(entry_premium * 100, 2), underlying_target, underlying_stop,
                strike - entry_premium if option_type == "PUT" else strike + entry_premium,
                put_variant or "outright", spread,
            )

        return DirectionalCandidate(
            run_at=run_at,
            ticker=ticker,
            option_type=option_type,
            strike=round(strike, 2),
            expiry=expiry_date,
            dte=dte_actual,
            entry_premium=round(entry_premium, 2),
            max_loss_per_contract=round(entry_premium * 100, 2),
            underlying_entry=round(underlying_entry, 2),
            underlying_target=round(underlying_target, 2) if underlying_target else None,
            underlying_stop=round(underlying_stop, 2) if underlying_stop else None,
            delta_abs=round(delta_abs, 3),
            current_price=round(price, 2),
            atm_iv_pct=round(atm_iv_pct, 1) if atm_iv_pct else None,
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
            invalidation_text=invalidation_text(c.option_type, c.underlying_stop),
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

        # Flow evidence (untested context). The per-ticker lookup uses
        # the flow engine's own per-ticker worker, _fetch_ticker_flow
        # (the worker behind run_flow_scan); the old import of a
        # get_flow_signals_for_tickers function that does not exist
        # failed on every run and was silently swallowed. A failure
        # here is now logged as a warning and the signals are set to
        # None explicitly, never left as a stale value.
        try:
            from services.options_flow_engine import _fetch_ticker_flow
            for c in candidates:
                try:
                    signals = _fetch_ticker_flow(c.ticker)
                except Exception as e:
                    logger.warning("Flow lookup failed for %s: %s", c.ticker, e)
                    c.flow_signals_json = None
                    continue
                c.flow_signals_json = json.dumps(signals) if signals else None
        except Exception as e:
            logger.warning("Flow engine import failed, flow signals unavailable: %s", e)
            for c in candidates:
                c.flow_signals_json = None


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
