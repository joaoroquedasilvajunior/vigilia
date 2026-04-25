from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/vigilia"
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    anthropic_api_key: str = ""

    camara_api_base_url: str = "https://dadosabertos.camara.leg.br/api/v2"
    camara_rate_limit_per_sec: float = 2.0
    camara_legislature: int = 57

    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
