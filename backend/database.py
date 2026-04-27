import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


def _build_url() -> str:
    """
    Use DATABASE_URL (PostgreSQL) when provided — this is the persistent store on Render.
    Fall back to SQLite for local development.
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()

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
    from models import recommendation, wheel, account, watchlist  # noqa: F401
    Base.metadata.create_all(bind=engine)
