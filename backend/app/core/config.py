"""Application settings, read from the environment (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""  # legacy HS256 projects only; blank → JWKS verification

    # Login
    employee_email_domain: str = "employees.kaarigar.app"
    seed_admin_password: str = ""

    # App
    allowed_origins: str = "http://localhost:5173"
    app_env: str = "development"
    languages_file: str = ""  # optional; default: <repo root>/shared/languages.json

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def employee_email(self, employee_id: str, plant_slug: str) -> str:
        """Hidden login email: <employee_id lowercased>@<plant_slug>.<domain>."""
        return f"{employee_id.lower()}@{plant_slug}.{self.employee_email_domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
