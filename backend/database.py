import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


def _build_url() -> str:
    """
    Use DATABASE_URL (PostgreSQL) when provided — this is the persistent store on Render.
    Fall back to SQLite for local development.

    Checks os.environ first, then pydantic settings (which also reads env vars),
    so it works regardless of how the variable is injected.
    """
    # Primary: raw os.environ (always reflects Render/system env vars at startup)
    database_url = os.environ.get("DATABASE_URL", "").strip()

    # Secondary: pydantic settings value (also reads env vars, belt-and-suspenders)
    if not database_url:
        database_url = (settings.database_url or "").strip()

    if database_url:
        # Render Postgres gives postgres:// but SQLAlchemy needs postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # Local dev: SQLite
    path = settings.db_path
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return f"sqlite:///{path}"


_url = _build_url()
_is_postgres = _url.startswith("postgresql")

engine = create_engine(
    _url,
    **({"pool_pre_ping": True, "pool_recycle": 300} if _is_postgres else {"connect_args": {"check_same_thread": False}}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import logging
    _log = logging.getLogger(__name__)

    # Diagnostic: show what DATABASE_URL was found (first 30 chars only)
    _raw_env = os.environ.get("DATABASE_URL", "")
    if _raw_env:
        _log.info("DATABASE: DATABASE_URL env var found, starts with: %s...", _raw_env[:30])
    else:
        _log.warning("DATABASE: DATABASE_URL env var is NOT set in os.environ")

    if _is_postgres:
        _log.info("DATABASE: connected to PostgreSQL (Neon) — data is persistent ✓")
    else:
        _log.warning(
            "DATABASE: using SQLite at %s — data will be lost on redeploy! "
            "Set DATABASE_URL=postgresql://... in your Render environment variables.",
            _url,
        )

    from models import recommendation, wheel, account, watchlist, champion, leveraged_ma, iv_snapshot, setup_registry, setup_alert, directional_candidate, champion_pick, challenge, rule_registry, run_receipt  # noqa: F401
    Base.metadata.create_all(bind=engine)
    try:
        _migrate_add_columns()
    except Exception as e:
        _log.warning("Column migration skipped: %s", e)


def _migrate_add_columns():
    """Safely add new columns to existing tables without dropping data."""
    from sqlalchemy import text
    additions = [
        ("wheel_recommendations", "assignment_chance_pct",    "FLOAT"),
        ("wheel_recommendations", "assignment_risk",          "VARCHAR(10)"),
        # Dual wheel modes: strategy mode per position (wheel vs harvest)
        ("wheel_positions", "mode", "VARCHAR(10) DEFAULT 'wheel'"),
        # Leveraged MA confirmation state machine (added after initial deploy)
        ("leveraged_ma_signal_state", "confirmed_position",  "VARCHAR(5)"),
        ("leveraged_ma_signal_state", "pending_signal",      "VARCHAR(5)"),
        ("leveraged_ma_signal_state", "pending_days",        "INTEGER"),
        # Account-aware sizing on alert cards (Priority 2)
        ("setup_alerts", "account_equity",       "FLOAT"),
        ("setup_alerts", "equity_source",        "VARCHAR(20)"),
        ("setup_alerts", "position_size_shares", "INTEGER"),
        ("setup_alerts", "risk_dollars",         "FLOAT"),
        ("setup_alerts", "risk_pct_actual",      "FLOAT"),
        ("setup_alerts", "sizing_note",          "TEXT"),
        ("setup_alerts", "sizing_source",        "VARCHAR(20)"),
        # Wheel premium priced at the bid (Oct 26 2026 fix)
        ("wheel_recommendations", "premium_source", "VARCHAR(20)"),
        # P1 rule registry and alert contract (Oct 27 2026)
        ("setup_alerts", "rule_key", "VARCHAR(80)"),
        ("setup_alerts", "exit_rule", "TEXT"),
        ("setup_alerts", "entry_source", "VARCHAR(30)"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in additions:
            try:
                if _is_postgres:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    ))
                else:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    ))
                conn.commit()
            except Exception:
                conn.rollback()
