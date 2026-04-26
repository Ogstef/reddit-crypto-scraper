"""Confirms the Pydantic DTOs serialize to the camelCase keys that Java Jackson expects."""

from datetime import UTC, datetime

from sentiment_scraper.models import (
    CryptoPanicIngestRequest,
    CryptoPanicPost,
    CryptoPanicVotes,
    RedditIngestRequest,
    RedditPost,
)


def test_reddit_post_serializes_camel_case():
    post = RedditPost(
        external_id="t3_aaa",
        subreddit="Bitcoin",
        title="x",
        body="y",
        score=10,
        num_comments=5,
        created_utc=datetime(2026, 4, 24, tzinfo=UTC),
        permalink="/r/Bitcoin/comments/aaa/x/",
        pair_hints=["BTC-EUR"],
    )
    wire = post.model_dump(by_alias=True, mode="json")
    assert "externalId" in wire
    assert "numComments" in wire
    assert "createdUtc" in wire
    assert "pairHints" in wire
    # Python-side names must NOT leak.
    assert "external_id" not in wire


def test_reddit_request_nests():
    req = RedditIngestRequest(
        posts=[], scraped_at=datetime(2026, 4, 24, tzinfo=UTC)
    )
    wire = req.model_dump(by_alias=True, mode="json")
    assert "scrapedAt" in wire
    assert wire["posts"] == []


def test_cryptopanic_votes_defaults():
    post = CryptoPanicPost(
        external_id="1",
        title="x",
        url="http://x",
        votes=CryptoPanicVotes(positive=5, negative=1),
        currency_codes=["BTC"],
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
    )
    wire = post.model_dump(by_alias=True, mode="json")
    assert wire["votes"]["positive"] == 5
    assert wire["votes"]["important"] == 0
    assert wire["currencyCodes"] == ["BTC"]


def test_cryptopanic_request_nests():
    req = CryptoPanicIngestRequest(posts=[], scraped_at=datetime.now(UTC))
    wire = req.model_dump(by_alias=True, mode="json")
    assert "scrapedAt" in wire
