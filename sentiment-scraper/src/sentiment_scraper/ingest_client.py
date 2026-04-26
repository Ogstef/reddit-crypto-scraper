"""HTTP client for the Java ingest endpoint.

Synchronous — simpler lifecycle + matches APScheduler's default executor.
Retries 5xx / connection errors with exponential backoff.
4xx: logs and raises (those are payload / config bugs, not transient).
"""

from __future__ import annotations

import logging
import time

import httpx

from .config import Settings
from .models import (
    CryptoPanicIngestRequest,
    IngestResponse,
    RedditIngestRequest,
)

log = logging.getLogger(__name__)


class IngestError(Exception):
    """Permanent ingest failure (4xx, or max retries exceeded on 5xx)."""


class IngestClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.ingest_url_base,
            timeout=settings.request_timeout_seconds,
            headers={
                "Authorization": settings.bearer_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def post_reddit(self, payload: RedditIngestRequest) -> IngestResponse:
        return self._post(
            "/api/sentiment/ingest/reddit",
            payload.model_dump(by_alias=True, mode="json"),
        )

    def post_cryptopanic(self, payload: CryptoPanicIngestRequest) -> IngestResponse:
        return self._post(
            "/api/sentiment/ingest/cryptopanic",
            payload.model_dump(by_alias=True, mode="json"),
        )

    # ─── Internal ────────────────────────────────────────────────────────

    def _post(self, path: str, body: dict) -> IngestResponse:
        attempt = 0
        last_status: int | None = None
        last_body: str = ""
        while attempt <= self._settings.max_retries:
            attempt += 1
            try:
                response = self._client.post(path, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                log.warning("[ingest] %s attempt %d network error: %s", path, attempt, exc)
                self._backoff(attempt)
                continue

            if 200 <= response.status_code < 300:
                return IngestResponse.model_validate(response.json())

            if 400 <= response.status_code < 500:
                raise IngestError(
                    f"{path} returned {response.status_code}: {response.text[:500]}"
                )

            last_status = response.status_code
            last_body = response.text[:200]
            log.warning(
                "[ingest] %s attempt %d returned %d — retrying",
                path, attempt, response.status_code,
            )
            self._backoff(attempt)

        raise IngestError(
            f"{path} failed after {self._settings.max_retries + 1} attempts; "
            f"last status={last_status} body={last_body!r}"
        )

    def _backoff(self, attempt: int) -> None:
        delay = min(2 ** (attempt - 1), 30)
        time.sleep(delay)
