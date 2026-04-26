"""Reddit scraper — pulls new.json from each configured subreddit.

Uses old.reddit.com's public ``.json`` endpoint. No OAuth, no tokens.
Rate-limited by User-Agent + a small delay between subs. If Reddit starts
blocking, swap this module for a Playwright-based renderer — the public
interface (``fetch()``) stays the same.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from ..config import Settings
from ..models import RedditPost
from .pair_matcher import match_pairs

log = logging.getLogger(__name__)

_API_TEMPLATE = "https://www.reddit.com/r/{subreddit}/new.json"


class RedditScraper:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Browser-like fingerprint — old.reddit.com + bot-style UA gets 403'd after a
        # few hours of scraping. www.reddit.com + a realistic browser UA + the headers
        # a real Chrome would send is the cheapest evasion that doesn't need Playwright.
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, per_sub_limit: int = 50) -> list[RedditPost]:
        """Scrape all configured subreddits. Returns typed RedditPosts.

        Errors on one sub do NOT abort the others.
        """
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

        data = response.json()
        children = (data.get("data") or {}).get("children") or []
        posts: list[RedditPost] = []
        for child in children:
            raw = child.get("data") or {}
            post = self._to_post(subreddit, raw)
            if post is not None:
                posts.append(post)
        log.info("[reddit] /r/%s: %d posts scraped", subreddit, len(posts))
        return posts

    def _to_post(self, subreddit: str, raw: dict) -> RedditPost | None:
        try:
            external_id = raw["name"]               # e.g. "t3_abc123"
            title = raw.get("title") or ""
            body = raw.get("selftext") or ""
            score = int(raw.get("score") or 0)
            num_comments = int(raw.get("num_comments") or 0)
            created_utc = datetime.fromtimestamp(float(raw["created_utc"]), tz=UTC)
            permalink = raw.get("permalink") or ""
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("[reddit] skipping malformed post in /r/%s: %s", subreddit, exc)
            return None

        pair_hints = match_pairs(title + "\n" + body, self._settings.pairs)
        return RedditPost(
            external_id=external_id,
            subreddit=subreddit,
            title=title,
            body=body,
            score=score,
            num_comments=num_comments,
            created_utc=created_utc,
            permalink=permalink,
            pair_hints=pair_hints,
        )
