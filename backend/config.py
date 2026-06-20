from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    google_maps_api_key: str = ""
    hunter_api_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "LeadGen Outreach"
    secret_key: str = "changeme"
    database_url: str = "sqlite:///./leadgen.db"
    max_emails_per_day: int = 50

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
