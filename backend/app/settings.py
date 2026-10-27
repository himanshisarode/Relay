"""All configuration comes from environment variables (prefix RELAY_). Nothing secret lives in the repo."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://relay:relay@localhost:5432/relay"
    base_url: str = "http://localhost:5173"
    timezone: str = "Asia/Kolkata"

    session_days: int = 7
    cookie_secure: bool = True
    # Dev only: return verification / reset tokens in API responses so the flow works without SMTP.
    dev_expose_tokens: bool = False
    rate_limit_enabled: bool = True
    # Shared secret for POST /api/internal/jobs/tick (AWS EventBridge). Empty disables the endpoint.
    cron_key: str = ""
    # On container start: "demo" loads seed + demo activity, "org" loads departments/labs/resources only.
    seed_on_start: str = ""
    # Comma-separated browser origins allowed to call the API with cookies. Only needed when the frontend talks to
    # the API on a different (sub)domain instead of through the Amplify /api proxy, e.g. "https://app.example.org".
    cors_origins: str = ""

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Relay <no-reply@relay.local>"
    smtp_starttls: bool = False

    access_request_expiry_days: int = 30
    waitlist_offer_minutes: int = 30
    reminder_minutes_before: int = 60
    series_horizon_weeks: int = 12

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
