"""Pydantic DTOs — mirror the Java @Valid request bodies 1:1.

Field names use ``snake_case`` internally; serialized as ``camelCase`` on the
wire (Java Jackson default). Controlled by ``populate_by_name`` + an alias
generator.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(w.capitalize() for w in rest)


class _Wire(BaseModel):
    """Base for all DTOs that cross the wire to Java."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
    )


# ─── Reddit ──────────────────────────────────────────────────────────────

class RedditPost(_Wire):
    external_id: str                                 # "t3_abc123"
    subreddit: str
    title: str
    body: str = ""
    score: int                                       # upvotes
    num_comments: int
    created_utc: datetime
    permalink: str
    pair_hints: list[str] = Field(default_factory=list)   # ["BTC-EUR", "ETH-EUR", …]


class RedditIngestRequest(_Wire):
    posts: list[RedditPost]
    scraped_at: datetime


# ─── CryptoPanic ─────────────────────────────────────────────────────────

class CryptoPanicVotes(_Wire):
    positive: int = 0
    negative: int = 0
    important: int = 0
    liked: int = 0
    disliked: int = 0


class CryptoPanicPost(_Wire):
    external_id: str
    title: str
    url: str
    votes: CryptoPanicVotes
    currency_codes: list[str] = Field(default_factory=list)    # ["BTC", "ETH", …]
    published_at: datetime


class CryptoPanicIngestRequest(_Wire):
    posts: list[CryptoPanicPost]
    scraped_at: datetime


# ─── Java response ───────────────────────────────────────────────────────

class IngestResponse(_Wire):
    """Mirrors the Java ``IngestResponse`` record — counts per ingest request."""

    received: int
    accepted: int
    deduped: int
    filtered: int
    classified: int = 0
