"""Maps free-form Reddit post text to one or more pair strings.

Deliberately permissive — if a post mentions multiple coins, it contributes to
multiple pairs' sentiment. Java's side still weights by volume, so this just
decides which (pair, source) rows a post becomes on the DB side.
"""

from __future__ import annotations

import re

# Canonical pair -> list of case-insensitive keyword stems.
# Using word boundaries so "btc" matches but "bitcoind" doesn't.
_KEYWORDS: dict[str, list[str]] = {
    "BTC-EUR": ["bitcoin", "btc", "xbt", "satoshi"],
    "ETH-EUR": ["ethereum", "eth", "ether", "vitalik"],
    "SOL-EUR": ["solana", "sol"],
}


def _compile(words: list[str]) -> re.Pattern[str]:
    pattern = r"(?i)(?<![A-Za-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![A-Za-z0-9])"
    return re.compile(pattern)


_COMPILED: dict[str, re.Pattern[str]] = {pair: _compile(words) for pair, words in _KEYWORDS.items()}


def match_pairs(text: str, pairs: list[str] | None = None) -> list[str]:
    """Return the pairs mentioned in ``text``.

    ``pairs`` limits the candidate set — if provided, only returns pairs that
    are both in this set AND matched by keyword.
    """
    if not text:
        return []
    candidates = pairs if pairs is not None else list(_KEYWORDS.keys())
    return [p for p in candidates if p in _COMPILED and _COMPILED[p].search(text)]
