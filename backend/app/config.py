from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./devpilot.db"
    jwt_secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 60
    ai_engine_url: str = "http://localhost:8001"
    upload_dir: str = "./var/uploads"
    cors_origins: str = "http://localhost:3000"
    auto_create_tables: bool = False
    log_level: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

