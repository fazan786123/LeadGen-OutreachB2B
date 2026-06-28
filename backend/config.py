from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    google_maps_api_key: str = ""

    # Brave Search — 2,000 free queries/month (search.brave.com/app/keys)
    brave_api_key: str = ""

    # Email finder API keys — add whichever you have, chain skips missing ones
    hunter_api_key: str = ""        # 25 free/month per key — hunter.io (comma-separate for multiple)
    apollo_api_key: str = ""        # 50 free/month per key — apollo.io (comma-separate for multiple)
    snov_client_id: str = ""        # 50 free/month per account — snov.io (comma-separate for multiple)
    snov_client_secret: str = ""
    skrapp_api_key: str = ""        # 100 free/month — skrapp.io
    findthat_api_key: str = ""      # 50 free/month  — findthat.email
    parallel_api_key: str = ""      # parallel.ai — deep web research, pay-as-you-go
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "LeadGen Outreach"
    secret_key: str = "changeme"
    database_url: str = "sqlite:///./leadgen.db"
    max_emails_per_day: int = 50

    class Config:
        env_file = (".env", "../.env")

    @property
    def hunter_api_keys(self) -> list[str]:
        return [k.strip() for k in self.hunter_api_key.split(",") if k.strip()]

    @property
    def apollo_api_keys(self) -> list[str]:
        return [k.strip() for k in self.apollo_api_key.split(",") if k.strip()]

    @property
    def snov_credentials(self) -> list[tuple[str, str]]:
        ids = [k.strip() for k in self.snov_client_id.split(",") if k.strip()]
        secrets = [k.strip() for k in self.snov_client_secret.split(",") if k.strip()]
        return [(i, s) for i, s in zip(ids, secrets) if i and s]


@lru_cache
def get_settings() -> Settings:
    return Settings()
