"""APScheduler entrypoint.

Runs forever. Two jobs:
  1. Reddit — every ``SCRAPER_REDDIT_INTERVAL_SECONDS`` (default 300 = 5 min).
  2. CryptoPanic — every ``SCRAPER_CRYPTOPANIC_INTERVAL_SECONDS`` (default 900 = 15 min).

Each job:
  - scrapes its source
  - filters through the dedup cache (SQLite)
  - chunks to ``SCRAPER_MAX_BATCH_SIZE``
  - POSTs to the Java ingest endpoint
  - marks seen only after a successful POST

Failures in one job NEVER affect the other.
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import UTC, datetime
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import Settings
from .cryptopanic.scraper import CryptoPanicScraper
from .dedup import DedupCache
from .ingest_client import IngestClient, IngestError
from .models import (
    CryptoPanicIngestRequest,
    CryptoPanicPost,
    RedditIngestRequest,
    RedditPost,
)
from .reddit.scraper import RedditScraper

log = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _chunk[T](items: list[T], size: int) -> list[list[T]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# ─── Per-source job bodies ──────────────────────────────────────────────

def _run_reddit_job(
    scraper: RedditScraper,
    dedup: DedupCache,
    client: IngestClient,
    batch_size: int,
) -> None:
    try:
        posts = scraper.fetch()
    except Exception as exc:   # noqa: BLE001
        log.error("[reddit] scrape failed: %s", exc, exc_info=True)
        return
    if not posts:
        log.info("[reddit] no posts scraped")
        return

    new_ids = dedup.filter_new("REDDIT", [p.external_id for p in posts])
    if not new_ids:
        log.info("[reddit] %d posts scraped — all deduped", len(posts))
        return

    new_id_set = set(new_ids)
    new_posts = [p for p in posts if p.external_id in new_id_set]
    _post_reddit_batches(new_posts, client, dedup, batch_size)


def _post_reddit_batches(
    posts: list[RedditPost],
    client: IngestClient,
    dedup: DedupCache,
    batch_size: int,
) -> None:
    for batch in _chunk(posts, batch_size):
        request = RedditIngestRequest(posts=batch, scraped_at=datetime.now(UTC))
        try:
            response = client.post_reddit(request)
        except IngestError as exc:
            log.error("[reddit] POST failed, dropping batch of %d: %s", len(batch), exc)
            continue
        log.info(
            "[reddit] ingested: received=%d accepted=%d deduped=%d filtered=%d classified=%d",
            response.received, response.accepted, response.deduped,
            response.filtered, response.classified,
        )
        dedup.mark_many("REDDIT", (p.external_id for p in batch))


def _run_cryptopanic_job(
    scraper: CryptoPanicScraper,
    dedup: DedupCache,
    client: IngestClient,
    batch_size: int,
) -> None:
    try:
        posts = scraper.fetch()
    except Exception as exc:   # noqa: BLE001
        log.error("[cryptopanic] scrape failed: %s", exc, exc_info=True)
        return
    if not posts:
        log.info("[cryptopanic] no posts scraped")
        return

    new_ids = dedup.filter_new("CRYPTOPANIC", [p.external_id for p in posts])
    if not new_ids:
        log.info("[cryptopanic] %d posts scraped — all deduped", len(posts))
        return

    new_id_set = set(new_ids)
    new_posts = [p for p in posts if p.external_id in new_id_set]
    _post_cryptopanic_batches(new_posts, client, dedup, batch_size)


def _post_cryptopanic_batches(
    posts: list[CryptoPanicPost],
    client: IngestClient,
    dedup: DedupCache,
    batch_size: int,
) -> None:
    for batch in _chunk(posts, batch_size):
        request = CryptoPanicIngestRequest(posts=batch, scraped_at=datetime.now(UTC))
        try:
            response = client.post_cryptopanic(request)
        except IngestError as exc:
            log.error("[cryptopanic] POST failed, dropping batch of %d: %s", len(batch), exc)
            continue
        log.info(
            "[cryptopanic] ingested: received=%d accepted=%d deduped=%d filtered=%d",
            response.received, response.accepted, response.deduped, response.filtered,
        )
        dedup.mark_many("CRYPTOPANIC", (p.external_id for p in batch))


# ─── Wiring ──────────────────────────────────────────────────────────────

def _install_shutdown_hooks(closers: list[Callable[[], None]]) -> None:
    def handler(sig, _frame) -> None:   # noqa: ANN001 — signal handler contract
        log.info("signal %s received — shutting down", sig)
        for close in closers:
            try:
                close()
            except Exception:   # noqa: BLE001
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def main() -> None:
    settings = Settings()
    _configure_logging(settings.log_level)

    if not settings.ingest_token.get_secret_value():
        log.error("SCRAPER_INGEST_TOKEN is not set — refusing to start")
        sys.exit(2)

    dedup = DedupCache(settings.dedup_db_path)
    reddit_scraper = RedditScraper(settings)
    cryptopanic_scraper = CryptoPanicScraper(settings)
    ingest = IngestClient(settings)

    _install_shutdown_hooks([reddit_scraper.close, cryptopanic_scraper.close, ingest.close])

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        _run_reddit_job,
        trigger="interval",
        seconds=settings.reddit_interval_seconds,
        args=[reddit_scraper, dedup, ingest, settings.max_batch_size],
        id="reddit",
        next_run_time=datetime.now(UTC),         # run immediately on startup
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_cryptopanic_job,
        trigger="interval",
        seconds=settings.cryptopanic_interval_seconds,
        args=[cryptopanic_scraper, dedup, ingest, settings.max_batch_size],
        id="cryptopanic",
        next_run_time=datetime.now(UTC),
        coalesce=True,
        max_instances=1,
    )

    log.info(
        "sentiment-scraper started — reddit every %ds, cryptopanic every %ds, ingest=%s",
        settings.reddit_interval_seconds,
        settings.cryptopanic_interval_seconds,
        settings.ingest_url_base,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
