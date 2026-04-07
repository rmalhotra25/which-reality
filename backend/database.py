import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


def _build_url() -> str:
    # Prefer an explicit DATABASE_URL (PostgreSQL on Neon/Supabase/Render)
    url = os.environ.get("DATABASE_URL") or settings.database_url
    if url:
        # Render/Heroku sometimes give postgres:// — SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    # Local fallback: SQLite
    path = settings.db_path
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return f"sqlite:///{path}"


_url = _build_url()
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(
    _url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,   # reconnect automatically if the connection drops
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
    from models import recommendation, wheel  # noqa: F401 — registers models
    Base.metadata.create_all(bind=engine)
