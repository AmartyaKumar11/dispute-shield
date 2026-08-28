from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    llm_api_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_api_key: str = ""
    llm_model_name: str = "kimi"

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./disputeshield.db"
    frontend_url: str = "http://localhost:5173"

    skip_webhook_validation: bool = True

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"


settings = Settings()
