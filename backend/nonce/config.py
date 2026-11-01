from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Turso / libSQL. Unset → a local SQLite file, so the project runs with no account.
    turso_database_url: str | None = None
    turso_auth_token: str | None = None
    local_db_path: str = str(BACKEND_DIR / "nonce.db")

    # The detector that produces signals (see signals.py): an HTTP service or a Python class.
    # Neither → every decision that needs signals goes to the user.
    signals_url: str | None = None
    signals_api_key: str | None = None
    signals_timeout_s: float = 3.0
    # With an OpenAI key (and no URL or class above): OpenAI's Decisions API with this model.
    signals_model: str = "gpt-6-luna"
    signals_detector: str | None = None

    # Luna (OpenAI) for Recall, the agent that searches your past questions in Cautious mode.
    # Or AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT. Unset → plain word matching.
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    luna_model: str = "gpt-6-luna"
    luna_fallback_model: str = "gpt-5.6-luna"
    luna_effort: Literal["low", "medium"] = "low"
    luna_timeout_s: float = 8.0

    # Fernet key that encrypts provider credentials (Google refresh tokens, Slack tokens) at rest.
    # PRIVATY_* names from before the rename still work.
    nonce_encryption_key: str = Field(validation_alias=AliasChoices("NONCE_ENCRYPTION_KEY", "PRIVATY_ENCRYPTION_KEY"))
    # Shared secret between the dashboard and this API; also signs approval links.
    nonce_admin_token: str = Field(validation_alias=AliasChoices("NONCE_ADMIN_TOKEN", "PRIVATY_ADMIN_TOKEN"))

    public_url: str = "http://localhost:8000"
    # Earlier public URLs: apps connected through them keep working without reconnecting.
    old_public_urls: list[str] = []
    dashboard_url: str = "http://localhost:3000"
    # Hosts the MCP endpoint accepts (DNS-rebinding protection); add your tunnel's host here.
    allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*"]

    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must exactly match a redirect URI on the Google OAuth client. Defaults to dashboard_url.
    google_redirect_uri: str | None = None

    # A Slack app with user token scopes search:read, channels:history, groups:history,
    # im:history, mpim:history. Its redirect URL is {DASHBOARD_URL}/oauth/slack.
    slack_client_id: str | None = None
    slack_client_secret: str | None = None

    # Text messages through Twilio. Verify confirms the user's number; Messaging sends approval
    # requests and needs a sending number or messaging service. Unset outside production → the
    # code and messages are printed to the server log instead.
    # Off until the Twilio account can send: hides the phone setting and sends no texts.
    sms_enabled: bool = False
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_verify_service_sid: str | None = None
    twilio_from_number: str | None = None
    twilio_messaging_service_sid: str | None = None
    production: bool = False

    # Push notifications through ntfy (https://ntfy.sh); unset → dashboard only.
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str | None = None

    # Web Push to the dashboard installed on a phone. Generate with `uv run python -m nonce.webpush`.
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    # Contact for the push services; defaults to the dashboard's address.
    vapid_subject: str | None = None

    # Policy limits
    default_ttl_s: int = 600
    max_auto_ttl_s: int = 3600
    hard_max_ttl_s: int = 86400
    default_max_calls: int = 30
    max_results_per_search: int = 25
    max_searches_per_minute: int = 10
    max_requests_per_hour: int = 12
    quiet_hours: tuple[int, int] = (0, 6)
    timezone: str = "America/Los_Angeles"


@lru_cache
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
