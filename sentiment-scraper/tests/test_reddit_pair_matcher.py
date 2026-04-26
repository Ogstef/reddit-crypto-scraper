from sentiment_scraper.reddit.pair_matcher import match_pairs


def test_matches_btc():
    assert "BTC-EUR" in match_pairs("Bitcoin to the moon, BTC rallying")


def test_matches_multiple():
    pairs = match_pairs("ETH and BTC both surging; Solana SOL too")
    assert set(pairs) == {"BTC-EUR", "ETH-EUR", "SOL-EUR"}


def test_ignores_substrings():
    # "bitcoind" or "bitcoinmaximalist" should NOT match "btc"
    # via word-boundary logic — the full word "bitcoin" DOES match though,
    # which is correct.
    assert match_pairs("bitcoinmaximalists") == []


def test_respects_pair_whitelist():
    # Even though "BTC" is mentioned, if we restrict candidates, we only
    # get ones in the whitelist.
    assert match_pairs("BTC news", pairs=["ETH-EUR"]) == []


def test_returns_empty_on_blank():
    assert match_pairs("") == []
    assert match_pairs("random unrelated text") == []
