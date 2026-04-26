"""BeautifulSoup parser for a CryptoPanic news listing page.

Selectors are the most fragile part of this service. When CryptoPanic changes
their HTML, this file is the only place that should need edits — plus the
saved fixture under ``tests/fixtures/``.

All selectors are expressed against the structure of ``https://cryptopanic.com/news/{CURRENCY}/``
as of the plan date (2026-04-24). If the listing is client-rendered and httpx
returns an empty body, the caller should switch to a headless-browser (Playwright)
fetch and pass the *rendered* HTML into ``parse_posts`` unchanged.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag

from ..models import CryptoPanicPost, CryptoPanicVotes

log = logging.getLogger(__name__)

# Known CryptoPanic DOM: each news item lives in `.news-row` with a
# `.news-cell` inner and data attribute `data-news-id` on the row.
# The votes block has per-reaction counters in `.pills-holder > .news-pill`.
_ROW_SELECTOR    = ".news-row"
_TITLE_SELECTOR  = ".news-cell-title a"
_CURRENCY_SEL    = ".colored-link"        # currency tags linked next to the title
_TIME_SELECTOR   = "time"
_VOTE_WRAP_SEL   = ".pills-holder"


def parse_posts(html: str, fallback_currency: str) -> list[CryptoPanicPost]:
    """Extract news posts from raw HTML.

    ``fallback_currency`` is used when a row has no explicit currency link
    (e.g. tagged to the page currency via URL path).
    """
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(_ROW_SELECTOR)
    if not rows:
        log.warning(
            "[cryptopanic] 0 rows matched — CryptoPanic may have changed HTML or the response "
            "is JS-rendered (upgrade to Playwright). snippet=%r",
            html[:200],
        )
        return []

    posts: list[CryptoPanicPost] = []
    for row in rows:
        post = _parse_row(row, fallback_currency)
        if post is not None:
            posts.append(post)
    return posts


def _parse_row(row: Tag, fallback_currency: str) -> CryptoPanicPost | None:
    external_id = row.get("data-news-id") or row.get("data-id")
    if not external_id:
        return None
    external_id = str(external_id)

    title_el = row.select_one(_TITLE_SELECTOR)
    if title_el is None:
        return None
    title = _clean_text(title_el.get_text())
    href = title_el.get("href") or ""
    url = _absolute(href)

    currency_codes = _extract_currency_codes(row) or [fallback_currency.upper()]

    votes = _extract_votes(row)
    published_at = _extract_published(row)

    return CryptoPanicPost(
        external_id=external_id,
        title=title,
        url=url,
        votes=votes,
        currency_codes=currency_codes,
        published_at=published_at,
    )


def _extract_currency_codes(row: Tag) -> list[str]:
    codes: list[str] = []
    for link in row.select(_CURRENCY_SEL):
        text = _clean_text(link.get_text())
        if text:
            # CryptoPanic uses uppercase tickers like "BTC", "ETH".
            codes.append(text.upper())
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _extract_votes(row: Tag) -> CryptoPanicVotes:
    positive = negative = important = liked = disliked = 0
    wrap = row.select_one(_VOTE_WRAP_SEL)
    if wrap is None:
        return CryptoPanicVotes()
    for pill in wrap.select(".news-pill"):
        label = (pill.get("title") or pill.get("aria-label") or "").lower()
        count = _extract_count(pill)
        # Order matters: "disliked" contains "liked" and "liked" contains "like",
        # so the more specific labels must be checked first.
        if "positive" in label or "bullish" in label:
            positive = count
        elif "negative" in label or "bearish" in label:
            negative = count
        elif "important" in label:
            important = count
        elif "dislike" in label or "toxic" in label:
            disliked = count
        elif "like" in label or "lol" in label:
            liked = count
    return CryptoPanicVotes(
        positive=positive,
        negative=negative,
        important=important,
        liked=liked,
        disliked=disliked,
    )


def _extract_published(row: Tag) -> datetime:
    time_el = row.select_one(_TIME_SELECTOR)
    if time_el is not None:
        raw = time_el.get("datetime") or time_el.get("title") or ""
        parsed = _parse_iso(raw)
        if parsed is not None:
            return parsed
    return datetime.now(UTC)


def _extract_count(pill: Tag) -> int:
    match = re.search(r"\d+", _clean_text(pill.get_text()))
    return int(match.group(0)) if match else 0


def _clean_text(s: str | None) -> str:
    return (s or "").strip()


def _absolute(href: str) -> str:
    if href.startswith("http"):
        return href
    return f"https://cryptopanic.com{href}" if href.startswith("/") else href


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    # CryptoPanic time tags use ISO 8601 with trailing "Z"; datetime.fromisoformat
    # accepts "+00:00" but not "Z" pre-Python 3.11. We run on 3.12, so direct.
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
