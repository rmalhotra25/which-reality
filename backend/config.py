import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    fmp_api_key: str = ""           # Financial Modeling Prep - used by 12 Step screener (free tier)
    database_url: str = ""          # PostgreSQL connection string (preferred)
    db_path: str = "../data/trading.db"   # SQLite fallback for local dev
    backend_port: int = 8000

    # TradeIQ login: set both to require HTTP Basic auth on every route
    # except /api/health and /api/keepalive. Leave both empty (default)
    # and the app stays open, as it is today. See backend/auth.py.
    tradeiq_auth_user: str = ""
    tradeiq_auth_password: str = ""
    # Bearer token alternative for scripts: Authorization: Bearer <token>
    tradeiq_auth_token: str = ""

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()
