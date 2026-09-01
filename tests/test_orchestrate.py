"""Tests for the concurrent source-fetch orchestration (newsletter.orchestrate)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import respx

from newsletter.models import (
    FetchFailure,
    FetchSuccess,
    RawRecord,
    Source,
)
from newsletter.orchestrate import fetch_all_sources

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

SIMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test</title>
    <link>https://example.com</link>
    <description>Test feed</description>
    <item>
      <title>Post</title>
      <link>https://example.com/post</link>
      <description>Hello</description>
    </item>
  </channel>
</rss>
"""


def _make_source(
    name: str = "S",
    url: str = "https://example.com/feed",
    *,
    fetch_type: str = "rss",
    enabled: bool = True,
) -> Source:
    return Source(
        name=name,
        scrape_url=url,
        priority="high",
        fetch_type=fetch_type,  # type: ignore[arg-type]
        category="general_ai",
        enabled=enabled,
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


class TestHappyPath:
    @respx.mock
    async def test_single_source_succeeds(self) -> None:
        src = _make_source(url="https://a.com/feed")
        respx.get("https://a.com/feed").mock(
            return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([src], client)

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, FetchSuccess)
        assert result.source is src
        assert len(result.records) == 1
        assert result.records[0].title == "Post"
        assert result.elapsed_ms > 0

    @respx.mock
    async def test_multiple_sources_all_succeed(self) -> None:
        sources = [
            _make_source(name=f"S{i}", url=f"https://host{i}.com/feed")
            for i in range(5)
        ]
        for i in range(5):
            respx.get(f"https://host{i}.com/feed").mock(
                return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
            )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources(sources, client)

        assert len(results) == 5
        assert all(isinstance(r, FetchSuccess) for r in results)
        for r in results:
            assert isinstance(r, FetchSuccess)
            assert len(r.records) == 1

    @respx.mock
    async def test_results_in_input_order(self) -> None:
        sources = [
            _make_source(name=f"Source{i}", url=f"https://host{i}.com/feed")
            for i in range(3)
        ]
        for i in range(3):
            respx.get(f"https://host{i}.com/feed").mock(
                return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
            )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources(sources, client)

        for i, result in enumerate(results):
            assert isinstance(result, FetchSuccess)
            assert result.source.name == f"Source{i}"


# --------------------------------------------------------------------------- #
# Fault isolation
# --------------------------------------------------------------------------- #


class TestFaultIsolation:
    @respx.mock
    async def test_one_failure_does_not_cancel_others(self) -> None:
        """A 404 on one source doesn't prevent others from succeeding."""
        ok = _make_source(name="OK", url="https://ok.com/feed")
        fail = _make_source(name="FAIL", url="https://fail.com/feed")

        respx.get("https://ok.com/feed").mock(
            return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
        )
        respx.get("https://fail.com/feed").mock(
            return_value=httpx.Response(404, text="not found")
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([ok, fail], client)

        assert len(results) == 2
        successes = [r for r in results if isinstance(r, FetchSuccess)]
        failures = [r for r in results if isinstance(r, FetchFailure)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert successes[0].source.name == "OK"
        assert failures[0].source.name == "FAIL"

    @respx.mock
    async def test_all_sources_fail(self) -> None:
        sources = [
            _make_source(name=f"Fail{i}", url=f"https://fail{i}.com/feed")
            for i in range(3)
        ]
        for i in range(3):
            respx.get(f"https://fail{i}.com/feed").mock(
                return_value=httpx.Response(500, text="server error")
            )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources(sources, client)

        assert len(results) == 3
        assert all(isinstance(r, FetchFailure) for r in results)

    @respx.mock
    async def test_failure_includes_elapsed_ms(self) -> None:
        src = _make_source(url="https://fail.com/feed")
        respx.get("https://fail.com/feed").mock(
            return_value=httpx.Response(500, text="error")
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([src], client)

        result = results[0]
        assert isinstance(result, FetchFailure)
        assert result.elapsed_ms > 0

    @respx.mock
    async def test_failure_includes_error_message(self) -> None:
        src = _make_source(url="https://fail.com/feed")
        respx.get("https://fail.com/feed").mock(
            return_value=httpx.Response(500, text="error")
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([src], client)

        result = results[0]
        assert isinstance(result, FetchFailure)
        assert "500" in result.error or "HTTP" in result.error


# --------------------------------------------------------------------------- #
# Disabled sources
# --------------------------------------------------------------------------- #


class TestDisabledSources:
    @respx.mock
    async def test_disabled_sources_skipped(self) -> None:
        enabled = _make_source(name="Enabled", enabled=True)
        disabled = _make_source(name="Disabled", enabled=False)

        # Only mock the enabled source's URL — if the disabled one were
        # fetched, respx would raise an unmocked request error.
        respx.get("https://example.com/feed").mock(
            return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([enabled, disabled], client)

        assert len(results) == 1
        assert isinstance(results[0], FetchSuccess)
        assert results[0].source.name == "Enabled"

    async def test_all_disabled_returns_empty(self) -> None:
        sources = [_make_source(enabled=False) for _ in range(3)]

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources(sources, client)

        assert results == []

    async def test_empty_source_list_returns_empty(self) -> None:
        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([], client)

        assert results == []


# --------------------------------------------------------------------------- #
# Unregistered fetcher type
# --------------------------------------------------------------------------- #


class TestUnregisteredFetcher:
    async def test_unknown_fetch_type_becomes_failure(self) -> None:
        src = _make_source(fetch_type="sitemap_or_search")

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([src], client)

        assert len(results) == 1
        assert isinstance(results[0], FetchFailure)
        assert "sitemap_or_search" in results[0].error

    @respx.mock
    async def test_unknown_fetcher_does_not_block_other_sources(self) -> None:
        unknown = _make_source(name="Unknown", fetch_type="web_search_query")
        known = _make_source(name="Known", url="https://ok.com/feed")

        respx.get("https://ok.com/feed").mock(
            return_value=httpx.Response(200, content=SIMPLE_RSS.encode())
        )

        async with httpx.AsyncClient() as client:
            results = await fetch_all_sources([unknown, known], client)

        successes = [r for r in results if isinstance(r, FetchSuccess)]
        failures = [r for r in results if isinstance(r, FetchFailure)]
        assert len(successes) == 1
        assert successes[0].source.name == "Known"
        assert len(failures) == 1
        assert failures[0].source.name == "Unknown"


# --------------------------------------------------------------------------- #
# Per-source timeout
# --------------------------------------------------------------------------- #


class TestPerSourceTimeout:
    async def test_timeout_becomes_failure(self) -> None:
        """A fetcher that takes longer than source_timeout → FetchFailure."""
        src = _make_source(url="https://slow.com/feed")

        async def slow_fetch(
            source: Source,
            client: httpx.AsyncClient,
            *,
            cutoff: datetime | None = None,
        ) -> list[RawRecord]:
            await asyncio.sleep(10)
            return []

        slow_fetcher = AsyncMock()
        slow_fetcher.fetch = slow_fetch
        slow_fetcher.fetch_types = frozenset({"rss"})

        with patch("newsletter.orchestrate.get_fetcher", return_value=slow_fetcher):
            async with httpx.AsyncClient() as client:
                results = await fetch_all_sources([src], client, source_timeout=0.05)

        assert len(results) == 1
        assert isinstance(results[0], FetchFailure)
        assert "Timed out" in results[0].error
        assert results[0].elapsed_ms > 0


# --------------------------------------------------------------------------- #
# Concurrency limiting
# --------------------------------------------------------------------------- #


class TestConcurrencyLimit:
    async def test_semaphore_caps_parallel_fetches(self) -> None:
        """Verify that at most *concurrency* fetches run simultaneously."""
        n_sources = 6
        concurrency = 2
        sources = [
            _make_source(name=f"S{i}", url=f"https://h{i}.com/feed")
            for i in range(n_sources)
        ]

        max_concurrent = 0
        current_concurrent = 0

        async def tracking_fetch(
            source: Source, client: httpx.AsyncClient, *, cutoff: datetime | None = None
        ) -> list[RawRecord]:
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return []

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = tracking_fetch
        mock_fetcher.fetch_types = frozenset({"rss"})

        with patch("newsletter.orchestrate.get_fetcher", return_value=mock_fetcher):
            async with httpx.AsyncClient() as client:
                results = await fetch_all_sources(
                    sources, client, concurrency=concurrency
                )

        assert len(results) == n_sources
        assert all(isinstance(r, FetchSuccess) for r in results)
        assert max_concurrent <= concurrency

    async def test_default_concurrency_allows_parallelism(self) -> None:
        """With concurrency=10 and 5 sources, all can run in parallel."""
        n_sources = 5
        sources = [
            _make_source(name=f"S{i}", url=f"https://h{i}.com/feed")
            for i in range(n_sources)
        ]

        max_concurrent = 0
        current_concurrent = 0

        async def tracking_fetch(
            source: Source, client: httpx.AsyncClient, *, cutoff: datetime | None = None
        ) -> list[RawRecord]:
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return []

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = tracking_fetch
        mock_fetcher.fetch_types = frozenset({"rss"})

        with patch("newsletter.orchestrate.get_fetcher", return_value=mock_fetcher):
            async with httpx.AsyncClient() as client:
                await fetch_all_sources(sources, client)

        # All 5 should have been able to start before any finished.
        assert max_concurrent == n_sources


# --------------------------------------------------------------------------- #
# Cutoff forwarding
# --------------------------------------------------------------------------- #


class TestCutoffForwarding:
    async def test_cutoff_passed_to_fetcher(self) -> None:
        src = _make_source()
        cutoff = datetime(2025, 1, 1, tzinfo=UTC)

        received_cutoff = None

        async def capturing_fetch(
            source: Source,
            client: httpx.AsyncClient,
            *,
            cutoff: datetime | None = None,
        ) -> list[RawRecord]:
            nonlocal received_cutoff
            received_cutoff = cutoff
            return []

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch = capturing_fetch
        mock_fetcher.fetch_types = frozenset({"rss"})

        with patch("newsletter.orchestrate.get_fetcher", return_value=mock_fetcher):
            async with httpx.AsyncClient() as client:
                await fetch_all_sources([src], client, cutoff=cutoff)

        assert received_cutoff == cutoff
