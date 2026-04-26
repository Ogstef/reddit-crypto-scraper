"""Reddit scraper — JSON endpoint with optional proxy + adaptive rate limiting.

The ``/r/{sub}/new.json`` endpoint exposes real engagement metrics (`score`,
`num_comments`) which the RSS feed lacks. JSON is reliably 403'd from
datacenter IPs, but works through a residential-IP proxy.

Egress strategy:
- If ``SCRAPER_HTTP_PROXY`` is set, all Reddit requests are routed through it.
- If unset, requests go out direct (works fine from a residential network).

Rate limiting follows Reddit's documented headers
(``X-Ratelimit-Remaining`` / ``X-Ratelimit-Reset``) — per the redditscraping
skill's adaptive-sleep formula. We're nowhere near the cap with our cadence
(4 reqs / 5 min), but the logic is defensive insurance for future scale.
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

_API_TEMPLATE = "https://old.reddit.com/r/{subreddit}/new.json"

# Reddit's anonymous rate is ~100 reqs / 10-min window. Floor sleep at 1s, ceiling
# at 10s — past 10s we're being needlessly slow.
_RATE_LIMIT_FLOOR_SEC = 1.0
_RATE_LIMIT_CEIL_SEC  = 10.0
# When budget gets critically low, pause until window resets (capped to 10.5 min).
_RATE_LIMIT_CRITICAL_THRESHOLD = 5.0
_RATE_LIMIT_PAUSE_CAP_SEC = 630.0


class RedditScraper:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        proxy = settings.http_proxy.strip() or None
        if proxy:
            log.info("[reddit] egress via proxy %s", proxy)

        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept":          "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            },
            cookies={
                # NSFW + quarantine bypass — required for some subs even if our list
                # doesn't include them; Reddit redirects/403s without these.
                "over18": "1",
                "_options": "%7B%22pref_quarantine_optin%22%3A+true%7D",
            },
            proxy=proxy,
            follow_redirects=True,
        )
        self._next_sleep_sec = 2.0

    def close(self) -> None:
        self._client.close()

    def fetch(self, per_sub_limit: int = 50) -> list[RedditPost]:
        """Scrape all configured subreddits. Errors on one sub do not abort the others."""
        results: list[RedditPost] = []
        for index, subreddit in enumerate(self._settings.reddit_subreddits):
            if index > 0:
                time.sleep(self._next_sleep_sec)
            try:
                results.extend(self._fetch_sub(subreddit, per_sub_limit))
            except Exception as exc:   # noqa: BLE001 — isolate per-sub failures
                log.warning("[reddit] /r/%s scrape failed: %s", subreddit, exc)
        return results

    # ─── Internal ────────────────────────────────────────────────────────

    def _fetch_sub(self, subreddit: str, limit: int) -> list[RedditPost]:
        url = _API_TEMPLATE.format(subreddit=subreddit)
        for attempt in range(4):
            response = self._client.get(url, params={"limit": limit})
            if response.status_code == 429:
                self._handle_429(response, subreddit, attempt)
                continue
            response.raise_for_status()
            self._update_rate_state(response)
            break
        else:
            log.warning("[reddit] /r/%s — gave up after 4 attempts (429)", subreddit)
            return []

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

        return RedditPost(
            external_id=external_id,
            subreddit=subreddit,
            title=title,
            body=body,
            score=score,
            num_comments=num_comments,
            created_utc=created_utc,
            permalink=permalink,
            pair_hints=match_pairs(title + "\n" + body, self._settings.pairs),
        )

    # ─── Adaptive rate limiting ──────────────────────────────────────────

    def _update_rate_state(self, response: httpx.Response) -> None:
        """Adjust per-request sleep based on Reddit's rate-limit headers.

        Headers are present on JSON endpoints; missing on HTML/RSS. When
        absent (or unparseable), we keep the previous sleep value.
        """
        try:
            remaining = float(response.headers["X-Ratelimit-Remaining"])
            reset     = float(response.headers["X-Ratelimit-Reset"])
        except (KeyError, ValueError):
            return

        if remaining <= _RATE_LIMIT_CRITICAL_THRESHOLD:
            wait = min(reset + 2.0, _RATE_LIMIT_PAUSE_CAP_SEC)
            log.warning(
                "[reddit] rate limit critical — %.0f remaining, pausing %.0fs", remaining, wait
            )
            time.sleep(wait)
            self._next_sleep_sec = 2.0
            return

        # Spread remaining budget evenly: sleep = window_reset / requests_left.
        self._next_sleep_sec = max(
            _RATE_LIMIT_FLOOR_SEC, min(reset / remaining, _RATE_LIMIT_CEIL_SEC)
        )

    def _handle_429(self, response: httpx.Response, subreddit: str, attempt: int) -> None:
        retry_after = float(response.headers.get("Retry-After", 30))
        wait = max(retry_after, 30.0 * (2 ** attempt))
        log.warning("[reddit] /r/%s 429 — backing off %.0fs (attempt %d)", subreddit, wait, attempt + 1)
        time.sleep(wait)
