import logging
from datetime import date, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

EASTERN = pytz.timezone("America/New_York")
# Weekdays only — holiday check happens inside the job before running
RUN_TIMES = [(9, 0), (9, 45), (12, 0), (15, 0), (18, 0)]


# ---------------------------------------------------------------------------
# NYSE holiday calendar
# ---------------------------------------------------------------------------

def _easter(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(114 + h + l - 7 * m, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> date:
    """If holiday falls on Saturday → Friday; Sunday → Monday."""
    if d.weekday() == 5:   # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:   # Sunday
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of weekday (0=Mon) in the given month/year."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of weekday in the given month/year."""
    # Start from last day of month and work back
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def nyse_holidays(year: int) -> set[date]:
    """Return the set of NYSE market holidays for the given year."""
    easter = _easter(year)
    good_friday = easter - timedelta(days=2)

    holidays = {
        # New Year's Day
        _observed(date(year, 1, 1)),
        # Martin Luther King Jr. Day — 3rd Monday of January
        _nth_weekday(year, 1, 0, 3),
        # Presidents' Day — 3rd Monday of February
        _nth_weekday(year, 2, 0, 3),
        # Good Friday
        good_friday,
        # Memorial Day — last Monday of May
        _last_weekday(year, 5, 0),
        # Juneteenth — June 19 (observed)
        _observed(date(year, 6, 19)),
        # Independence Day — July 4 (observed)
        _observed(date(year, 7, 4)),
        # Labor Day — 1st Monday of September
        _nth_weekday(year, 9, 0, 1),
        # Thanksgiving — 4th Thursday of November
        _nth_weekday(year, 11, 3, 4),
        # Christmas — December 25 (observed)
        _observed(date(year, 12, 25)),
    }
    return holidays


def is_trading_day(d: date | None = None) -> bool:
    """Return True if the given date (default: today Eastern) is an NYSE trading day."""
    if d is None:
        d = date.today()   # caller should pass Eastern-local date
    if d.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    return d not in nyse_holidays(d.year)


# ---------------------------------------------------------------------------
# Scheduler jobs
# ---------------------------------------------------------------------------

def run_all_analyses() -> None:
    from database import SessionLocal
    from services.options_engine import OptionsEngine
    from services.wheel_engine import WheelEngine

    today_eastern = date.today()   # server runs in UTC; check via pytz below
    import datetime as _dt
    today_eastern = _dt.datetime.now(EASTERN).date()

    if not is_trading_day(today_eastern):
        logger.info(
            "Scheduler: skipping run on %s — not a trading day (weekend or NYSE holiday)",
            today_eastern,
        )
        return

    logger.info("Scheduler: starting all analysis pipelines for %s", today_eastern)
    db = SessionLocal()
    try:
        OptionsEngine(db).run()
        WheelEngine(db).run()
    except Exception as e:
        logger.error("Scheduled run failed: %s", e, exc_info=True)
    finally:
        db.close()

    # Snap ATM IV for the universe after each analysis run
    db2 = SessionLocal()
    try:
        from services.iv_snapshot_service import snap_iv_universe
        result = snap_iv_universe(db2)
        logger.info("Scheduler: IV snapshot complete: %s", result)
    except Exception as e:
        logger.error("IV snapshot run failed: %s", e, exc_info=True)
    finally:
        db2.close()


def run_champions_scan() -> None:
    from database import SessionLocal
    from services.champions_engine import run as run_champions
    import datetime as _dt

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping champions scan — not a trading day")
        return

    logger.info("Scheduler: running daily champions scan")
    db = SessionLocal()
    try:
        run_champions(db)
    except Exception as e:
        logger.error("Champions scan failed: %s", e, exc_info=True)
    finally:
        db.close()


def run_discovery_scan_job() -> None:
    """Run the buy-and-hold discovery scan — fires once daily pre-market."""
    import datetime as _dt

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping discovery scan — not a trading day")
        return

    logger.info("Scheduler: running daily discovery scan")
    from services.discovery_engine import trigger_scan
    try:
        trigger_scan(force=True)
        logger.info("Scheduler: discovery scan launched in background thread")
    except Exception as e:
        logger.error("Discovery scan failed to launch: %s", e, exc_info=True)


def run_alert_engine_job() -> None:
    """Evaluate all setup signals and journal any alerts. Runs after market close."""
    import datetime as _dt
    from database import SessionLocal

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping alert engine -- not a trading day")
        return

    logger.info("Scheduler: running setup alert engine")
    db = SessionLocal()
    try:
        from services.alert_engine import run_alert_engine
        result = run_alert_engine(db)
        logger.info("Scheduler: alert engine complete: %s", result)
    except Exception as e:
        logger.error("Alert engine failed: %s", e, exc_info=True)
        import services.run_status as run_status
        run_status.set_error("alert_engine", str(e))
    finally:
        db.close()


def run_alert_outcome_job() -> None:
    """Mark open alerts closed when target/stop/time-stop is hit."""
    import datetime as _dt
    from database import SessionLocal

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping alert outcome job -- not a trading day")
        return

    logger.info("Scheduler: running alert outcome job")
    db = SessionLocal()
    try:
        from services.alert_journal_service import run_outcome_job
        result = run_outcome_job(db)
        logger.info("Scheduler: alert outcome job complete: %s", result)
    except Exception as e:
        logger.error("Alert outcome job failed: %s", e, exc_info=True)
        import services.run_status as run_status
        run_status.set_error("alert_journal", str(e))
    finally:
        db.close()


def run_champion_outcome_job() -> None:
    """Settle open champion picks that have reached their horizon."""
    import datetime as _dt
    from database import SessionLocal

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping champion outcome job -- not a trading day")
        return

    logger.info("Scheduler: running champion outcome job")
    db = SessionLocal()
    try:
        from services.champion_journal_service import run_outcome_job
        result = run_outcome_job(db)
        logger.info("Scheduler: champion outcome job complete: %s", result)
    except Exception as e:
        logger.error("Champion outcome job failed: %s", e, exc_info=True)
        import services.run_status as run_status
        run_status.set_error("champion_journal", str(e))
    finally:
        db.close()


def run_wheel_scanner_job() -> None:
    """Run the wheel put + call scanner after market open and mid-afternoon."""
    import datetime as _dt
    from database import SessionLocal

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping wheel scanner -- not a trading day")
        return

    logger.info("Scheduler: running wheel scanner")
    db = SessionLocal()
    try:
        from services.wheel_scanner_service import run_put_scanner, run_call_scanner
        run_put_scanner(db)
        run_call_scanner(db)
        logger.info("Scheduler: wheel scanner complete")
    except Exception as e:
        logger.error("Wheel scanner failed: %s", e, exc_info=True)
        import services.run_status as run_status
        run_status.set_error("wheel_scanner", str(e))
    finally:
        db.close()


def run_challenge_snapshot_job() -> None:
    """Snapshot the challenge account after the close; no-op if uninitialized."""
    from database import SessionLocal

    logger.info("Scheduler: running challenge snapshot")
    db = SessionLocal()
    try:
        from services import challenge_service
        if challenge_service.get_account(db) is None:
            logger.info("Scheduler: challenge account not initialized -- skipping")
            return
        challenge_service.take_snapshot(db)
        logger.info("Scheduler: challenge snapshot complete")
    except Exception as e:
        logger.error("Challenge snapshot failed: %s", e, exc_info=True)
    finally:
        db.close()


def refresh_call_suggestions() -> None:
    from database import SessionLocal
    from services.wheel_engine import WheelEngine
    import datetime as _dt

    today_eastern = _dt.datetime.now(EASTERN).date()
    if not is_trading_day(today_eastern):
        logger.info("Scheduler: skipping call suggestion refresh — not a trading day")
        return

    logger.info("Scheduler: refreshing weekly call suggestions")
    db = SessionLocal()
    try:
        WheelEngine(db).refresh_all_call_suggestions()
    except Exception as e:
        logger.error("Call suggestion refresh failed: %s", e, exc_info=True)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=EASTERN)

    for hour, minute in RUN_TIMES:
        scheduler.add_job(
            run_all_analyses,
            # day_of_week="mon-fri" fires the job — trading day check happens inside
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=EASTERN),
            id=f"analysis_{hour:02d}{minute:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )

    # Daily 9:10 AM Eastern — champions scan (one batched Claude call)
    scheduler.add_job(
        run_champions_scan,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=10, timezone=EASTERN),
        id="champions_daily",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Daily 6:00 AM Eastern — discovery scan (full-universe buy-and-hold
    # crawl), so results are ready at market open
    scheduler.add_job(
        run_discovery_scan_job,
        CronTrigger(day_of_week="mon-fri", hour=6, minute=0, timezone=EASTERN),
        id="discovery_scan_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Daily 17:30 ET -- setup alert engine (after close, uses end-of-day prices)
    scheduler.add_job(
        run_alert_engine_job,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=30, timezone=EASTERN),
        id="alert_engine_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Daily 8:00 AM ET -- alert outcome job (before open, marks exits from prior day close)
    scheduler.add_job(
        run_alert_outcome_job,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=EASTERN),
        id="alert_outcome_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Daily 8:15 AM ET -- champion outcome job (after the alert outcome job,
    # settles champion picks that reached their horizon, so the Book
    # scoreboard stops reading 0 settled forever)
    scheduler.add_job(
        run_champion_outcome_job,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=15, timezone=EASTERN),
        id="champion_outcome_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Wheel scanner: 10:30 AM and 14:00 Eastern (after open + mid-afternoon)
    for scanner_hour, scanner_minute in [(10, 30), (14, 0)]:
        scheduler.add_job(
            run_wheel_scanner_job,
            CronTrigger(
                day_of_week="mon-fri",
                hour=scanner_hour,
                minute=scanner_minute,
                timezone=EASTERN,
            ),
            id=f"wheel_scanner_{scanner_hour:02d}{scanner_minute:02d}",
            replace_existing=True,
            misfire_grace_time=1800,
        )

    # Daily 17:15 ET -- challenge account snapshot (end-of-day equity,
    # stage graduation check); does nothing until the account exists
    scheduler.add_job(
        run_challenge_snapshot_job,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=15, timezone=EASTERN),
        id="challenge_snapshot_daily",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Weekly Tuesday 9:05 AM Eastern — refresh covered call suggestions
    # (Monday could be a holiday, so Tuesday is safer)
    scheduler.add_job(
        refresh_call_suggestions,
        CronTrigger(day_of_week="tue", hour=9, minute=5, timezone=EASTERN),
        id="call_suggestions_weekly",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Jobs fire Mon-Fri at %s Eastern (skips NYSE holidays automatically).",
        ", ".join(f"{h:02d}:{m:02d}" for h, m in RUN_TIMES),
    )
    return scheduler
