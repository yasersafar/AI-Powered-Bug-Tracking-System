from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Security / JWT
    SECRET_KEY: str = "dev-only-change-me-in-the-env-file-please"  # override in .env
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # Database
    DATABASE_URL: str = "sqlite:///./bugtracker.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
