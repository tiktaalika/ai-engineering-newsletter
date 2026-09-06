"""Tests for newsletter.dedup — URL normalization."""

from __future__ import annotations

from newsletter.dedup import norm_url


class TestNormUrl:
    def test_strips_utm_parameters(self) -> None:
        result = norm_url(
            "https://example.com/a?utm_source=feed&utm_medium=rss&utm_campaign=x"
        )
        assert result == "https://example.com/a"

    def test_strips_utm_case_insensitively(self) -> None:
        result = norm_url("https://example.com/a?UTM_SOURCE=x&ref=keep")
        assert result == "https://example.com/a?ref=keep"

    def test_keeps_non_utm_query_parameters(self) -> None:
        result = norm_url("https://example.com/a?id=42&ref=feed&utm_source=x")
        assert result == "https://example.com/a?id=42&ref=feed"

    def test_lowercases_netloc(self) -> None:
        assert norm_url("https://EXAMPLE.Com/Path") == "https://example.com/Path"

    def test_strips_trailing_path_slash(self) -> None:
        assert norm_url("https://example.com/a/") == "https://example.com/a"

    def test_drops_fragment(self) -> None:
        assert norm_url("https://example.com/a#section") == "https://example.com/a"

    def test_drops_blank_query_values(self) -> None:
        assert norm_url("https://example.com/a?foo=") == "https://example.com/a"

    def test_empty_string(self) -> None:
        assert norm_url("") == ""

    def test_idempotent(self) -> None:
        url = "https://Example.com/a/?utm_source=x&id=1#frag"
        once = norm_url(url)
        assert norm_url(once) == once
