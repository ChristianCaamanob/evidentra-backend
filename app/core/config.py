from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Evidentra Backend MVP"
    environment: str = "development"
    # En producción Railway/Render sobreescribe DATABASE_URL con PostgreSQL.
    # En local usa SQLite por defecto.
    database_url: str = "sqlite:///./evidentra_mvp.db"
    # CORS_ORIGINS como string separado por comas en la variable de entorno.
    # Valor "*" permite cualquier origen (necesario para el HTML estático).
    cors_origins_str: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_origins_str.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins_str.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
