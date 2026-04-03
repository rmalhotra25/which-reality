import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


def _resolve_db_path() -> str:
    path = settings.db_path
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


engine = create_engine(
    f"sqlite:///{_resolve_db_path()}",
    connect_args={"check_same_thread": False},
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
