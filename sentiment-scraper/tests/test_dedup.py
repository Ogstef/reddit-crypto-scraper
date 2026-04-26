from sentiment_scraper.dedup import DedupCache


def test_is_new_empty(tmp_path):
    cache = DedupCache(tmp_path / "dedup.sqlite")
    assert cache.is_new("REDDIT", "t3_xxx") is True


def test_mark_and_is_new(tmp_path):
    cache = DedupCache(tmp_path / "dedup.sqlite")
    cache.mark_many("REDDIT", ["t3_a", "t3_b"])
    assert cache.is_new("REDDIT", "t3_a") is False
    assert cache.is_new("REDDIT", "t3_c") is True
    # Different source, same id — independent
    assert cache.is_new("CRYPTOPANIC", "t3_a") is True


def test_filter_new(tmp_path):
    cache = DedupCache(tmp_path / "dedup.sqlite")
    cache.mark_many("REDDIT", ["a", "b"])
    assert cache.filter_new("REDDIT", ["a", "b", "c", "d"]) == ["c", "d"]
    assert cache.filter_new("REDDIT", []) == []


def test_survives_reopen(tmp_path):
    path = tmp_path / "dedup.sqlite"
    DedupCache(path).mark_many("REDDIT", ["persist"])
    assert DedupCache(path).is_new("REDDIT", "persist") is False
