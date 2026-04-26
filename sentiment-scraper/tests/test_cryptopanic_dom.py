from datetime import UTC, datetime
from pathlib import Path

from sentiment_scraper.cryptopanic.dom import parse_posts


def _fixture() -> str:
    return (Path(__file__).parent / "fixtures" / "cryptopanic_btc.html").read_text()


def test_parse_posts_basic():
    posts = parse_posts(_fixture(), fallback_currency="BTC")
    assert len(posts) == 2


def test_extracts_first_post():
    post = parse_posts(_fixture(), fallback_currency="BTC")[0]
    assert post.external_id == "1001"
    assert post.title == "Bitcoin hits new all-time high"
    assert post.url == "https://cryptopanic.com/news/1001/Bitcoin-ATH"
    assert post.currency_codes == ["BTC"]
    assert post.votes.positive == 12
    assert post.votes.negative == 3
    assert post.votes.important == 5
    assert post.votes.liked == 7
    assert post.votes.disliked == 1
    assert post.published_at == datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)


def test_extracts_multi_currency():
    second = parse_posts(_fixture(), fallback_currency="BTC")[1]
    assert second.currency_codes == ["BTC", "ETH"]
    assert second.votes.positive == 8
    assert second.votes.important == 0    # not present in fixture


def test_empty_body_returns_empty():
    assert parse_posts("<html><body></body></html>", fallback_currency="BTC") == []


def test_fallback_currency_when_none_found():
    html = """
    <div class="news-row" data-news-id="42">
      <div class="news-cell-title"><a href="/news/42/x">Title</a></div>
      <time datetime="2026-04-24T10:00:00Z">10:00</time>
    </div>
    """
    post = parse_posts(html, fallback_currency="SOL")[0]
    assert post.currency_codes == ["SOL"]
