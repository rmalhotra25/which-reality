import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    db_path: str = "../data/trading.db"
    backend_port: int = 8000

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()
