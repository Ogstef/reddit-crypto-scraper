"""CryptoPanic scraper — fetches per-currency news pages and parses via dom.py.

CryptoPanic aggressively challenges plain HTTP clients. We send realistic
browser headers, but if the server returns 403 or the parsed page yields no
posts, we log loudly and return an empty list rather than silently succeeding.

Next-step fallback (not implemented in v1): replace ``_fetch_html`` with a
Playwright-driven render. The ``parse_posts`` contract stays identical — HTML
string in, typed posts out.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..config import Settings
from ..models import CryptoPanicPost
from .dom import parse_posts

log = logging.getLogger(__name__)

# Realistic browser headers — CryptoPanic 403s plain ``python-httpx/x.y`` UAs.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Drop "br" (Brotli) — httpx doesn't decompress it without the optional `brotli`
    # dep, and CryptoPanic sends Brotli when offered. gzip/deflate is enough.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class CryptoPanicScraper:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers=_BROWSER_HEADERS,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self) -> list[CryptoPanicPost]:
        """Scrape all configured currency pages. Isolates per-currency failures."""
        all_posts: list[CryptoPanicPost] = []
        for index, currency in enumerate(self._settings.cryptopanic_currencies):
            if index > 0:
                time.sleep(3)   # polite delay
            try:
                all_posts.extend(self._fetch_currency(currency))
            except Exception as exc:   # noqa: BLE001 — isolate per-currency failures
                log.warning("[cryptopanic] %s scrape failed: %s", currency, exc)
        return all_posts

    def _fetch_currency(self, currency: str) -> list[CryptoPanicPost]:
        html = self._fetch_html(currency)
        if not html:
            return []
        posts = parse_posts(html, fallback_currency=currency)
        log.info("[cryptopanic] %s: %d posts scraped", currency, len(posts))
        return posts

    def _fetch_html(self, currency: str) -> str:
        url = f"{self._settings.cryptopanic_base_url.rstrip('/')}/news/{currency}/"
        response = self._client.get(url)
        if response.status_code == 403:
            log.warning(
                "[cryptopanic] 403 on %s — CryptoPanic is blocking plain HTTP clients. "
                "Consider switching _fetch_html to a Playwright renderer.",
                url,
            )
            return ""
        if response.status_code == 429:
            log.warning("[cryptopanic] 429 on %s — backing off", url)
            return ""
        response.raise_for_status()
        return response.text
