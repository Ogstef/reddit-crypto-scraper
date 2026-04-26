"""Settings loaded from env / .env via pydantic-settings.

All settings use the prefix ``SCRAPER_`` so they can't collide with unrelated env.
"""

from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ingest target ────────────────────────────────────────────────────
    ingest_base_url: str = "http://localhost:8089"
    ingest_token: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer token matching sentiment.ingest.auth-token",
    )

    # ── Cadences ─────────────────────────────────────────────────────────
    reddit_interval_seconds: int = 300
    cryptopanic_interval_seconds: int = 900

    # ── HTTP ─────────────────────────────────────────────────────────────
    request_timeout_seconds: int = 30
    max_retries: int = 3

    # ── Outbound scraping proxy (for VPS deploys behind a reverse SSH tunnel) ─
    # When set, Reddit requests are routed through this HTTP proxy so they
    # appear to originate from a residential IP rather than the VPS's
    # datacenter IP (which Reddit blocks at the network layer).
    # Env var: SCRAPER_HTTP_PROXY. Empty (default) means direct egress.
    http_proxy: str = ""

    # ── Batching ─────────────────────────────────────────────────────────
    max_batch_size: int = 100

    # ── Reddit ───────────────────────────────────────────────────────────
    # NoDecode disables pydantic-settings' default JSON-decode for list fields,
    # so the env value can be a plain CSV like "Bitcoin,ethereum,…" instead of
    # a JSON-array literal. The field_validator below splits it.
    reddit_user_agent: str = "revolut-trading-bot-scraper/0.1 (by /u/stefo)"
    reddit_subreddits: Annotated[list[str], NoDecode] = [
        "CryptoCurrency",
        "Bitcoin",
        "ethereum",
        "solana",
        "CryptoMarkets",
    ]

    # ── CryptoPanic ──────────────────────────────────────────────────────
    cryptopanic_currencies: Annotated[list[str], NoDecode] = ["BTC", "ETH", "SOL"]
    cryptopanic_base_url: str = "https://cryptopanic.com"

    # ── Pair mapping ─────────────────────────────────────────────────────
    pairs: Annotated[list[str], NoDecode] = ["BTC-EUR", "ETH-EUR", "SOL-EUR"]

    # ── Dedup ────────────────────────────────────────────────────────────
    # Default lives under XDG cache so the local dev path needs no sudo.
    # The Docker image overrides this to /var/lib/sentiment-scraper/dedup.sqlite
    # via Dockerfile's volume mount.
    dedup_db_path: str = str(Path.home() / ".cache" / "sentiment-scraper" / "dedup.sqlite")

    # ── Logging ──────────────────────────────────────────────────────────
    log_level: str = "INFO"

    @field_validator("reddit_subreddits", "cryptopanic_currencies", "pairs", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow comma-separated env values, e.g. SCRAPER_PAIRS=BTC-EUR,ETH-EUR.

        Empty strings (e.g. ``SCRAPER_CRYPTOPANIC_CURRENCIES=``) become an empty
        list, which is a useful kill-switch for disabling a source.
        """
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def ingest_url_base(self) -> str:
        return self.ingest_base_url.rstrip("/")

    @property
    def bearer_header(self) -> str:
        return f"Bearer {self.ingest_token.get_secret_value()}"
