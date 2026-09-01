"""Tests for the CLI entry point and pipeline orchestration (newsletter.main)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from newsletter.main import (
    _resolve_config_path,
    _setup_logging,
    app,
    collect_candidates,
    raw_record_to_candidate,
)
from newsletter.models import (
    Engagement,
    FetchFailure,
    FetchSuccess,
    RawRecord,
    Source,
)

runner = CliRunner()

# Minimal valid TOML config with one source — used by CLI tests that need
# the pipeline to reach the mocked fetch stage.
_MINIMAL_CONFIG = (
    'user_agent = "test-agent/1.0"\n'
    "[priority_presets]\n"
    "high = 1.0\n"
    "medium = 0.65\n"
    "low = 0.35\n"
    "[category_window_hours]\n"
    "general_ai = 24\n"
    "engineering_ai = 720\n"
    "research = 168\n"
    "startup = 72\n"
    "vendor = 72\n"
    "community = 48\n"
    "\n"
    "[[sources]]\n"
    'name = "Test"\n'
    'scrape_url = "https://example.com/feed"\n'
    'priority = "high"\n'
    'fetch_type = "rss"\n'
    'category = "general_ai"\n'
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def test_source() -> Source:
    return Source(
        name="Test Feed",
        scrape_url="https://example.com/feed",
        priority="high",
        fetch_type="rss",
        category="general_ai",
        tags=["test"],
    )


@pytest.fixture()
def test_record(test_source: Source) -> RawRecord:
    return RawRecord(
        source=test_source,
        title="AI Breakthrough Announced",
        url="https://example.com/ai-breakthrough",
        description="A major AI breakthrough has been announced today.",
        pub_date=datetime(2025, 9, 1, 12, 0, tzinfo=UTC),
        engagement=Engagement(points=100, comments=25, upvotes=500),
    )


# --------------------------------------------------------------------------- #
# raw_record_to_candidate
# --------------------------------------------------------------------------- #


class TestRawRecordToCandidate:
    def test_basic_conversion(
        self, test_source: Source, test_record: RawRecord
    ) -> None:
        candidate = raw_record_to_candidate(test_source, test_record)

        assert candidate.title == "AI Breakthrough Announced"
        assert candidate.url == "https://example.com/ai-breakthrough"
        assert candidate.source is test_source
        assert candidate.category == "general_ai"
        assert candidate.pub_date == datetime(2025, 9, 1, 12, 0, tzinfo=UTC)
        assert candidate.text == test_record.description
        assert candidate.engagement.points == 100
        assert candidate.engagement.comments == 25
        assert candidate.engagement.upvotes == 500
        assert candidate.score_breakdown.score == 0.0
        assert candidate.registry_category == "general_ai"
        assert candidate.source_priority == "high"

    def test_generates_unique_ids(
        self, test_source: Source, test_record: RawRecord
    ) -> None:
        c1 = raw_record_to_candidate(test_source, test_record)
        c2 = raw_record_to_candidate(test_source, test_record)
        assert c1.id != c2.id
        assert len(c1.id) == 36  # UUID4 string length
        assert len(c2.id) == 36


# --------------------------------------------------------------------------- #
# collect_candidates
# --------------------------------------------------------------------------- #


class TestCollectCandidates:
    async def test_converts_successes(
        self, test_source: Source, test_record: RawRecord
    ) -> None:
        """FetchSuccess results produce candidates."""
        mock_config = AsyncMock()
        mock_config.sources = [test_source]

        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[FetchSuccess(source=test_source, records=[test_record])],
        ):
            async with httpx.AsyncClient() as client:
                candidates = await collect_candidates(client, mock_config)

        assert len(candidates) == 1
        assert candidates[0].title == "AI Breakthrough Announced"

    async def test_skips_failures(self, test_source: Source) -> None:
        """FetchFailure results are logged but produce no candidates."""
        mock_config = AsyncMock()
        mock_config.sources = [test_source]

        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[FetchFailure(source=test_source, error="connection refused")],
        ):
            async with httpx.AsyncClient() as client:
                candidates = await collect_candidates(client, mock_config)

        assert candidates == []

    async def test_mixed_results(self, test_source: Source) -> None:
        """Both successes and failures in the same result list."""
        source_a = Source(
            name="A",
            scrape_url="https://a.com/feed",
            priority="high",
            fetch_type="rss",
            category="general_ai",
        )
        source_b = Source(
            name="B",
            scrape_url="https://b.com/feed",
            priority="medium",
            fetch_type="rss",
            category="general_ai",
        )

        record = RawRecord(
            source=source_a,
            title="Good News",
            url="https://a.com/good",
            description="Something good happened.",
        )

        mock_config = AsyncMock()
        mock_config.sources = [source_a, source_b]

        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[
                FetchSuccess(source=source_a, records=[record]),
                FetchFailure(source=source_b, error="timeout"),
            ],
        ):
            async with httpx.AsyncClient() as client:
                candidates = await collect_candidates(client, mock_config)

        assert len(candidates) == 1
        assert candidates[0].source is source_a

    async def test_empty_results(self, test_source: Source) -> None:
        """No results → no candidates."""
        mock_config = AsyncMock()
        mock_config.sources = [test_source]

        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[],
        ):
            async with httpx.AsyncClient() as client:
                candidates = await collect_candidates(client, mock_config)

        assert candidates == []


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


class TestResolveConfigPath:
    def test_explicit_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.toml"
        assert _resolve_config_path(custom) == custom.resolve()

    def test_default_path(self) -> None:
        result = _resolve_config_path(None)
        assert result.name == "config.toml"
        assert "config" in str(result)


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #


class TestSetupLogging:
    def test_missing_logging_toml_falls_back(self, tmp_path: Path) -> None:
        """When logging.toml doesn't exist, basicConfig is used."""
        (tmp_path / "config").mkdir()
        _setup_logging(tmp_path)  # should not raise

    def test_creates_logs_directory(self, tmp_path: Path) -> None:
        _setup_logging(tmp_path)
        assert (tmp_path / "logs").is_dir()


# --------------------------------------------------------------------------- #
# CLI (Typer)
# --------------------------------------------------------------------------- #


class TestCLI:
    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert (
            "newsletter" in result.output.lower() or "collect" in result.output.lower()
        )

    def test_missing_config_exits_1(self, tmp_path: Path) -> None:
        """A non-existent config file causes exit code 1."""
        fake_config = tmp_path / "nonexistent.toml"
        result = runner.invoke(app, ["--config", str(fake_config)])
        assert result.exit_code == 1

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_collect_with_valid_config(
        self, mock_fetch: AsyncMock, tmp_path: Path
    ) -> None:
        """Successful collect with a valid config exits 0."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        mock_fetch.return_value = []

        result = runner.invoke(app, ["--config", str(config_file)])
        assert result.exit_code == 0

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_dry_run_flag(self, mock_fetch: AsyncMock, tmp_path: Path) -> None:
        """--dry-run exits 0 and still fetches."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        mock_fetch.return_value = []

        result = runner.invoke(app, ["--config", str(config_file), "--dry-run"])
        assert result.exit_code == 0
        mock_fetch.assert_called_once()

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_window_hours_option(self, mock_fetch: AsyncMock, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        mock_fetch.return_value = []

        result = runner.invoke(
            app, ["--config", str(config_file), "--window-hours", "48"]
        )
        assert result.exit_code == 0

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_date_option(self, mock_fetch: AsyncMock, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        mock_fetch.return_value = []

        result = runner.invoke(
            app, ["--config", str(config_file), "--date", "2025-09-15"]
        )
        assert result.exit_code == 0

    def test_invalid_date_exits_nonzero(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)

        result = runner.invoke(
            app, ["--config", str(config_file), "--date", "not-a-date"]
        )
        assert result.exit_code != 0

    def test_no_sources_exits_1(self, tmp_path: Path) -> None:
        """Config with zero sources exits 1."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            'user_agent = "test-agent/1.0"\n'
            "[priority_presets]\n"
            "high = 1.0\n"
            "medium = 0.65\n"
            "low = 0.35\n"
            "[category_window_hours]\n"
            "general_ai = 24\n"
        )

        result = runner.invoke(app, ["--config", str(config_file)])
        assert result.exit_code == 1


# --------------------------------------------------------------------------- #
# Signal handling
# --------------------------------------------------------------------------- #


class TestSignalHandling:
    async def test_cancelled_pipeline_returns_130(self) -> None:
        """When the pipeline task is cancelled, exit code is 130."""

        async def slow_fetch(
            sources: list,
            client: httpx.AsyncClient,
            **kwargs: object,
        ) -> list:
            await asyncio.sleep(60)
            return []

        mock_config = AsyncMock()
        mock_config.sources = [
            Source(
                name="Slow",
                scrape_url="https://slow.com/feed",
                priority="high",
                fetch_type="rss",
                category="general_ai",
            )
        ]
        mock_config.user_agent = "test/1.0"

        async def run_and_cancel() -> int:
            task = asyncio.current_task()

            # Schedule cancellation after a short delay.
            async def cancel_soon() -> None:
                await asyncio.sleep(0.05)
                task.cancel()  # type: ignore[union-attr]

            asyncio.ensure_future(cancel_soon())

            try:
                with patch(
                    "newsletter.main.fetch_all_sources",
                    new_callable=AsyncMock,
                    side_effect=slow_fetch,
                ):
                    async with httpx.AsyncClient() as client:
                        await collect_candidates(client, mock_config)
                return 0
            except asyncio.CancelledError:
                return 130

        exit_code = await run_and_cancel()
        assert exit_code == 130
