"""Reddit scraper — pulls posts from each configured subreddit via Atom RSS.

Reddit's `.json` endpoint is reliably 403'd from datacenter IPs (we hit this on
the VPS within seconds of the first request). The public Atom RSS feed at
``/r/{sub}/.rss`` is less restricted and works from datacenter IPs.

Trade-off: RSS doesn't expose ``score`` or ``num_comments``, so we default
those to a value that passes any reasonable backend filter (10/10). Cost is
still bounded by the classifier's hard ``€3/month`` budget cap on the Java side.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..models import RedditPost
from .pair_matcher import match_pairs

log = logging.getLogger(__name__)

_API_TEMPLATE = "https://www.reddit.com/r/{subreddit}/.rss"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class RedditScraper:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
                ),
                # RSS feed wants XML, not JSON
                "Accept": "application/atom+xml, application/xml; q=0.9, */*; q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, per_sub_limit: int = 50) -> list[RedditPost]:
        """Scrape all configured subreddits. Errors on one sub do not abort the others."""
        results: list[RedditPost] = []
        for index, subreddit in enumerate(self._settings.reddit_subreddits):
            if index > 0:
                time.sleep(2)   # polite delay between subs
            try:
                results.extend(self._fetch_sub(subreddit, per_sub_limit))
            except Exception as exc:   # noqa: BLE001 — isolate per-sub failures
                log.warning("[reddit] /r/%s scrape failed: %s", subreddit, exc)
        return results

    # ─── Internal ────────────────────────────────────────────────────────

    def _fetch_sub(self, subreddit: str, limit: int) -> list[RedditPost]:
        url = _API_TEMPLATE.format(subreddit=subreddit)
        response = self._client.get(url, params={"limit": limit})
        if response.status_code == 429:
            log.warning("[reddit] 429 on /r/%s — backing off", subreddit)
            return []
        response.raise_for_status()

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            log.warning("[reddit] /r/%s RSS parse failed: %s", subreddit, exc)
            return []

        posts: list[RedditPost] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            post = self._entry_to_post(subreddit, entry)
            if post is not None:
                posts.append(post)
        log.info("[reddit] /r/%s: %d posts scraped", subreddit, len(posts))
        return posts

    def _entry_to_post(self, subreddit: str, entry: ET.Element) -> RedditPost | None:
        external_id = _text(entry.find("atom:id", _ATOM_NS))
        title       = _text(entry.find("atom:title", _ATOM_NS))
        if not external_id or not title:
            return None

        body_html = _text(entry.find("atom:content", _ATOM_NS))
        body = _strip_html(body_html)

        updated_raw = _text(entry.find("atom:updated", _ATOM_NS))
        created_utc = _parse_iso(updated_raw) or datetime.now(UTC)

        link_el = entry.find("atom:link", _ATOM_NS)
        permalink = link_el.get("href") if link_el is not None else ""

        # RSS doesn't expose score / num_comments. Defaults are high enough that
        # every entry passes the backend's pre-filter; cost stays bounded by
        # the classifier's monthly budget cap.
        return RedditPost(
            external_id=external_id,
            subreddit=subreddit,
            title=title,
            body=body,
            score=10,
            num_comments=10,
            created_utc=created_utc,
            permalink=permalink,
            pair_hints=match_pairs(title + "\n" + body, self._settings.pairs),
        )


# ─── Module helpers ──────────────────────────────────────────────────────

def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
