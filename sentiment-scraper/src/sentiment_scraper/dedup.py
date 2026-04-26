"""Persistent dedup cache — never re-POST the same (source, external_id) to Java.

SQLite so the cache survives restarts. One table, one PK, ~10 μs per hit.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class DedupCache:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    source      TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    first_seen  TEXT NOT NULL,
                    PRIMARY KEY (source, external_id)
                )
                """
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self._path, isolation_level=None)   # autocommit
        try:
            yield cx
        finally:
            cx.close()

    def is_new(self, source: str, external_id: str) -> bool:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT 1 FROM seen WHERE source = ? AND external_id = ? LIMIT 1",
                (source, external_id),
            ).fetchone()
        return row is None

    def mark_many(self, source: str, external_ids: Iterable[str]) -> None:
        rows = [(source, eid, datetime.now(UTC).isoformat()) for eid in external_ids]
        if not rows:
            return
        with self._conn() as cx:
            cx.executemany(
                "INSERT OR IGNORE INTO seen(source, external_id, first_seen) VALUES (?, ?, ?)",
                rows,
            )

    def filter_new(self, source: str, external_ids: list[str]) -> list[str]:
        """Return only the ids that have never been seen for this source."""
        if not external_ids:
            return []
        with self._conn() as cx:
            placeholders = ",".join("?" * len(external_ids))
            rows = cx.execute(
                f"SELECT external_id FROM seen WHERE source = ? AND external_id IN ({placeholders})",
                (source, *external_ids),
            ).fetchall()
        already = {r[0] for r in rows}
        return [eid for eid in external_ids if eid not in already]
