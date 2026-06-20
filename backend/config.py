from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    google_maps_api_key: str = ""

    # Brave Search — 2,000 free queries/month (search.brave.com/app/keys)
    brave_api_key: str = ""

    # Email finder API keys — add whichever you have, chain skips missing ones
    hunter_api_key: str = ""        # 25 free/month  — hunter.io
    apollo_api_key: str = ""        # 50 free/month  — apollo.io
    snov_client_id: str = ""        # 50 free/month  — snov.io (needs id + secret)
    snov_client_secret: str = ""
    skrapp_api_key: str = ""        # 100 free/month — skrapp.io
    findthat_api_key: str = ""      # 50 free/month  — findthat.email
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
