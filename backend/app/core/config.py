"""Application settings, read from the environment (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.net_patch import maybe_force_ipv4

# Applied at config import — before any network client (Supabase, DB pool, HF hub) is built.
maybe_force_ipv4()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""  # legacy HS256 projects only; blank → JWKS verification
    database_url: str = ""  # Postgres (Supabase session pooler); Phase 1 search/ingest

    # Login
    employee_email_domain: str = "employees.kaarigar.app"
    seed_admin_password: str = ""

    # App
    allowed_origins: str = "http://localhost:5173"
    app_env: str = "development"
    languages_file: str = ""  # optional; default: <repo root>/shared/languages.json

    # Phase 1 — knowledge in
    groq_api_key: str = ""  # optional; without it Excel column mapping uses rules
    groq_model_small: str = "openai/gpt-oss-20b"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_enabled: bool = False
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    fastembed_cache_path: str = "./.cache/fastembed"
    max_pdf_mb: int = 25
    max_pdf_pages: int = 300
    max_log_mb: int = 5
    max_log_rows: int = 5000

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def employee_email(self, employee_id: str, plant_slug: str) -> str:
        """Hidden login email: <employee_id lowercased>@<plant_slug>.<domain>."""
        return f"{employee_id.lower()}@{plant_slug}.{self.employee_email_domain}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
