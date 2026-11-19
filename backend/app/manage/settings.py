"""Phase 4 settings. Reads the same .env as the rest of the backend."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ManageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_ENV: str = "development"
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""            # backend only, never in the frontend
    EMPLOYEE_EMAIL_DOMAIN: str = "employees.kaarigar.app"
    PUBLIC_APP_URL: str = "https://app.kaarigar-ai.online"   # QR stickers open PUBLIC_APP_URL/m/<qr_token>
    STICKERS_MAX: int = 60                          # per print request (5 A4 sheets)


@lru_cache
def get_manage_settings() -> ManageSettings:
    return ManageSettings()
