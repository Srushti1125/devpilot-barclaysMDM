from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./devpilot.db"

    # ── Authentication ──────────────────────────────────────────────────────
    jwt_secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 60

    # ── External Services ───────────────────────────────────────────────────
    ai_engine_url: str = "http://localhost:8001"

    # ── File Storage ────────────────────────────────────────────────────────
    upload_dir: str = "./var/uploads"
    storage_backend: str = "local"  # "local" | "s3" (future)

    # ── CORS ────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"

    # ── Operational ─────────────────────────────────────────────────────────
    auto_create_tables: bool = False
    log_level: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
