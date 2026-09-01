"""Tests for the RSS/Atom/RDF fetcher module."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from newsletter.fetchers import (
    FETCHER_REGISTRY,
    RSSFetcher,
    UnknownFetcherError,
    fetch_kind,
    get_fetcher,
)
from newsletter.fetchers.rss import (
    _clean_xml_entities,
    parse_pub_date,
)
from newsletter.http import HTTPStatusFetchError
from newsletter.models import Source

from .conftest import SAMPLE_ATOM, SAMPLE_RSS_20, SAMPLE_RSS_BARE_AMPERSAND

# --------------------------------------------------------------------------- #
# RSSFetcher unit tests
# --------------------------------------------------------------------------- #


class TestRSSFetcher:
    def test_fetch_types(self) -> None:
        fetcher = RSSFetcher()
        assert fetcher.fetch_types == frozenset({"rss", "atom", "rdf"})

    @respx.mock
    async def test_fetch_rss_20(self, rss_source: Source) -> None:
        """Parse a standard RSS 2.0 feed with two items."""
        respx.get(rss_source.scrape_url).mock(
            return_value=httpx.Response(200, content=SAMPLE_RSS_20.encode("utf-8"))
        )

        async with httpx.AsyncClient() as client:
            records = await RSSFetcher().fetch(rss_source, client)

        assert len(records) == 2

        assert records[0].title == "First Post"
        assert records[0].url == "https://blog.example.com/first-post"
        assert "Hello world" in records[0].description
        assert records[0].pub_date is not None
        assert records[0].pub_date.year == 2025
        assert records[0].pub_date.month == 9
        assert records[0].pub_date.day == 1
        assert records[0].source is rss_source

        assert records[1].title == "Second Post"
        assert records[1].url == "https://blog.example.com/second-post"

    @respx.mock
    async def test_fetch_atom(self, atom_source: Source) -> None:
        """Parse an Atom feed with one entry."""
        respx.get(atom_source.scrape_url).mock(
            return_value=httpx.Response(200, content=SAMPLE_ATOM.encode("utf-8"))
        )

        async with httpx.AsyncClient() as client:
            records = await RSSFetcher().fetch(atom_source, client)

        assert len(records) == 1
        assert records[0].title == "Atom Entry"
        assert records[0].url == "https://blog.example.com/atom-entry"
        assert "atom summary" in records[0].description

    @respx.mock
    async def test_fetch_bare_ampersand(self, rss_source: Source) -> None:
        """Bare ``&`` in XML is cleaned before parsing."""
        respx.get(rss_source.scrape_url).mock(
            return_value=httpx.Response(
                200, content=SAMPLE_RSS_BARE_AMPERSAND.encode("utf-8")
            )
        )

        async with httpx.AsyncClient() as client:
            records = await RSSFetcher().fetch(rss_source, client)

        assert len(records) == 1
        assert "AT&T" in records[0].title

    @respx.mock
    async def test_fetch_empty_feed(self, rss_source: Source) -> None:
        """An empty feed returns zero records."""
        empty_rss = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty</title>
    <link>https://example.com</link>
    <description>Empty feed</description>
  </channel>
</rss>
"""
        respx.get(rss_source.scrape_url).mock(
            return_value=httpx.Response(200, content=empty_rss)
        )

        async with httpx.AsyncClient() as client:
            records = await RSSFetcher().fetch(rss_source, client)

        assert records == []

    @respx.mock
    async def test_fetch_http_error(self, rss_source: Source) -> None:
        """Non-retryable HTTP errors raise HTTPStatusFetchError."""
        respx.get(rss_source.scrape_url).mock(
            return_value=httpx.Response(404, text="not found")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPStatusFetchError) as exc_info:
                await RSSFetcher().fetch(rss_source, client)

        assert exc_info.value.status_code == 404
        assert exc_info.value.url == rss_source.scrape_url


# --------------------------------------------------------------------------- #
# XML entity cleanup
# --------------------------------------------------------------------------- #


class TestCleanXmlEntities:
    def test_replaces_bare_ampersand(self) -> None:
        assert "&amp;" in _clean_xml_entities("foo & bar")

    def test_preserves_valid_entities(self) -> None:
        assert "&amp;" in _clean_xml_entities("&amp;")
        assert "&lt;" in _clean_xml_entities("&lt;")
        assert "&gt;" in _clean_xml_entities("&gt;")
        assert "&quot;" in _clean_xml_entities("&quot;")
        assert "&apos;" in _clean_xml_entities("&apos;")

    def test_preserves_numeric_entities(self) -> None:
        assert "&#123;" in _clean_xml_entities("&#123;")
        assert "&#x1F;" in _clean_xml_entities("&#x1F;")

    def test_no_change_needed(self) -> None:
        clean = "no ampersands here"
        assert _clean_xml_entities(clean) == clean


# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #


class TestParsePubDate:
    def test_rfc2822(self) -> None:
        dt = parse_pub_date("Mon, 01 Sep 2025 12:00:00 GMT")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 9
        assert dt.day == 1
        assert dt.tzinfo is not None

    def test_iso8601(self) -> None:
        dt = parse_pub_date("2025-09-01T10:00:00Z")
        assert dt is not None
        assert dt.hour == 10

    def test_iso8601_with_offset(self) -> None:
        dt = parse_pub_date("2025-09-01T10:00:00+05:30")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_date_only(self) -> None:
        dt = parse_pub_date("2025-09-01")
        assert dt is not None
        assert dt.day == 1

    def test_naive_datetime_gets_utc(self) -> None:
        dt = parse_pub_date(datetime(2025, 1, 1, tzinfo=None))  # noqa: DTZ001
        assert dt is not None
        assert dt.tzinfo == UTC

    def test_none_input(self) -> None:
        assert parse_pub_date(None) is None

    def test_empty_string(self) -> None:
        assert parse_pub_date("") is None

    def test_garbage_input(self) -> None:
        assert parse_pub_date("not a date at all") is None

    def test_non_string_input(self) -> None:
        assert parse_pub_date(42) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Fetcher registry & dispatch
# --------------------------------------------------------------------------- #


class TestRegistry:
    def test_rss_registered(self) -> None:
        assert "rss" in FETCHER_REGISTRY
        assert "atom" in FETCHER_REGISTRY
        assert "rdf" in FETCHER_REGISTRY

    def test_all_rss_types_same_instance(self) -> None:
        assert FETCHER_REGISTRY["rss"] is FETCHER_REGISTRY["atom"]
        assert FETCHER_REGISTRY["rss"] is FETCHER_REGISTRY["rdf"]

    def test_get_fetcher_rss(self, rss_source: Source) -> None:
        fetcher = get_fetcher(rss_source)
        assert isinstance(fetcher, RSSFetcher)

    def test_get_fetcher_atom(self, atom_source: Source) -> None:
        fetcher = get_fetcher(atom_source)
        assert isinstance(fetcher, RSSFetcher)

    def test_get_fetcher_unknown(self, website_source: Source) -> None:
        with pytest.raises(UnknownFetcherError, match="website"):
            get_fetcher(website_source)


class TestFetchKind:
    def test_explicit_fetch_type(self, rss_source: Source) -> None:
        assert fetch_kind(rss_source) == "rss"

    def test_fallback_rss_source_type(self) -> None:
        src = Source(
            name="S",
            scrape_url="https://example.com/feed",
            priority="low",
            fetch_type="rss",
            category="general_ai",
            source_type="rss",
        )
        assert fetch_kind(src) == "rss"

    def test_fallback_website_source_type(self) -> None:
        src = Source(
            name="S",
            scrape_url="https://example.com/",
            priority="low",
            fetch_type="web_search_query",
            category="general_ai",
            source_type="website",
        )
        # fetch_type is explicitly set, so it wins
        assert fetch_kind(src) == "web_search_query"
