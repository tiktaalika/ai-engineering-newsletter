"""Tests for newsletter.text — deterministic entry identifiers."""

from __future__ import annotations

from newsletter.dedup import norm_url
from newsletter.text import entry_id


class TestEntryId:
    def test_returns_16_hex_chars(self) -> None:
        result = entry_id("https://example.com/article", "Some Title")
        assert len(result) == 16
        int(result, 16)  # must be valid hex

    def test_deterministic(self) -> None:
        a = entry_id("https://example.com/article", "Title")
        b = entry_id("https://example.com/article", "Title")
        assert a == b

    def test_case_insensitive(self) -> None:
        a = entry_id("https://example.com/Article", "Title")
        b = entry_id("https://example.com/article", "Title")
        assert a == b

    def test_falls_back_to_title_when_url_empty(self) -> None:
        result = entry_id("", "Breaking AI News")
        assert len(result) == 16
        # Derived from the title, not the empty URL.
        assert result == entry_id("", "Breaking AI News")
        assert result != entry_id("", "Different Title")

    def test_url_wins_over_title(self) -> None:
        a = entry_id("https://example.com/a", "Title One")
        b = entry_id("https://example.com/a", "Title Two")
        assert a == b  # same URL → same ID regardless of title

    def test_different_urls_get_different_ids(self) -> None:
        a = entry_id("https://example.com/a", "Title")
        b = entry_id("https://example.com/b", "Title")
        assert a != b

    def test_normalized_equivalent_urls_share_id(self) -> None:
        """UTM variants and host case must collapse to one ID."""
        a = entry_id(norm_url("https://Example.com/a?utm_source=x&utm_campaign=y"), "T")
        b = entry_id(norm_url("https://example.com/a/"), "T")
        assert a == b

    def test_unicode_title_fallback(self) -> None:
        result = entry_id("", "Café AI — 中文标题")
        assert len(result) == 16
        int(result, 16)
