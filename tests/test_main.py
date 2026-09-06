"""Tests for the CLI entry point and pipeline orchestration (newsletter.main)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from newsletter import main as main_module
from newsletter.configuration import Configuration
from newsletter.keywords import KeywordConfig
from newsletter.main import (
    _install_signal_handlers,
    _resolve_config_path,
    _resolve_keywords_path,
    _resolve_output_dir,
    _setup_logging,
    app,
    collect_candidates,
    load_section_history,
)
from newsletter.models import (
    Engagement,
    FetchFailure,
    FetchSuccess,
    RawRecord,
    Source,
)

runner = CliRunner()

ConfigurationFactory = Callable[..., Configuration]

#: Fixed "now" so recency scoring and staleness gates are deterministic.
NOW = datetime(2025, 9, 1, 12, 0, tzinfo=UTC)

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
        pub_date=NOW,
        engagement=Engagement(points=100, comments=25, upvotes=500),
    )


# --------------------------------------------------------------------------- #
# collect_candidates
# --------------------------------------------------------------------------- #


class TestCollectCandidates:
    async def test_returns_candidates_and_run_log(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        test_source: Source,
        test_record: RawRecord,
    ) -> None:
        """Successes are filtered, scored, and reported in the run log."""
        config = make_configuration(sources=[test_source])
        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[FetchSuccess(source=test_source, records=[test_record])],
        ):
            async with httpx.AsyncClient() as client:
                candidates, run_log = await collect_candidates(
                    client, config, keyword_config, now=NOW
                )

        assert len(candidates) == 1
        assert candidates[0].title == "AI Breakthrough Announced"
        assert candidates[0].score_breakdown.score > 0.0
        assert run_log.fetched_count == 1
        assert run_log.filtered_count == 1
        assert run_log.duplicate_count == 0
        assert run_log.failures == []

    async def test_failures_are_logged_not_raised(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        test_source: Source,
    ) -> None:
        config = make_configuration(sources=[test_source])
        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[FetchFailure(source=test_source, error="connection refused")],
        ):
            async with httpx.AsyncClient() as client:
                candidates, run_log = await collect_candidates(
                    client, config, keyword_config, now=NOW
                )

        assert candidates == []
        assert run_log.failures == [
            {"source": "Test Feed", "error": "connection refused"}
        ]

    async def test_irrelevant_records_are_filtered(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        test_source: Source,
    ) -> None:
        """A record with no keyword hit never becomes a candidate."""
        record = RawRecord(
            source=test_source,
            title="Local council approves a bicycle lane",
            url="https://example.com/bicycle-lane",
            description="The lane opens next spring.",
            pub_date=NOW,
        )
        config = make_configuration(sources=[test_source])
        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[FetchSuccess(source=test_source, records=[record])],
        ):
            async with httpx.AsyncClient() as client:
                candidates, run_log = await collect_candidates(
                    client, config, keyword_config, now=NOW
                )

        assert candidates == []
        assert run_log.fetched_count == 1
        assert run_log.filtered_count == 0

    async def test_mixed_results(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        test_source: Source,
        test_record: RawRecord,
    ) -> None:
        other = Source(
            name="Broken Feed",
            scrape_url="https://b.com/feed",
            priority="medium",
            fetch_type="rss",
            category="general_ai",
        )
        config = make_configuration(sources=[test_source, other])
        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[
                FetchSuccess(source=test_source, records=[test_record]),
                FetchFailure(source=other, error="timeout"),
            ],
        ):
            async with httpx.AsyncClient() as client:
                candidates, run_log = await collect_candidates(
                    client, config, keyword_config, now=NOW
                )

        assert [candidate.source.name for candidate in candidates] == ["Test Feed"]
        assert run_log.source_count == 2
        assert len(run_log.failures) == 1

    async def test_empty_results(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        test_source: Source,
    ) -> None:
        config = make_configuration(sources=[test_source])
        with patch(
            "newsletter.main.fetch_all_sources",
            new_callable=AsyncMock,
            return_value=[],
        ):
            async with httpx.AsyncClient() as client:
                candidates, run_log = await collect_candidates(
                    client, config, keyword_config, now=NOW
                )

        assert candidates == []
        assert run_log.fetched_count == 0


# --------------------------------------------------------------------------- #
# Section history
# --------------------------------------------------------------------------- #


class TestLoadSectionHistory:
    def test_missing_directory_yields_empty_history(self, tmp_path: Path) -> None:
        history = load_section_history(tmp_path / "nope", "2026-09-01")
        assert set(history) == {
            "general_ai",
            "engineering_ai",
            "medical_bio_ai",
            "research",
        }
        assert all(items == [] for items in history.values())

    def test_reads_published_sections(self, tmp_path: Path) -> None:
        artifact = tmp_path / "2026-08-31-candidates.json"
        artifact.write_text(
            json.dumps(
                {
                    "top_10_general_ai": [
                        {
                            "id": "abc123",
                            "title": "Nvidia unveils a GPU",
                            "url": "https://a.com/1",
                            "source": "Outlet A",
                            "source_kind": "rss",
                            "category": "general_ai",
                            "source_priority": "high",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        history = load_section_history(tmp_path, "2026-09-01")
        assert len(history["general_ai"]) == 1
        assert history["general_ai"][0].title == "Nvidia unveils a GPU"
        # Outside the general-AI lookback would be empty for other sections.
        assert history["research"] == []


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


class TestResolveKeywordsPath:
    def test_explicit_path_wins(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom-keywords.toml"
        config_path = tmp_path / "config.toml"
        assert _resolve_keywords_path(custom, config_path) == custom.resolve()

    def test_sibling_of_config_is_preferred(self, tmp_path: Path) -> None:
        """A self-contained config directory keeps its own keywords."""
        (tmp_path / "config.toml").write_text("", encoding="utf-8")
        sibling = tmp_path / "keywords.toml"
        sibling.write_text("", encoding="utf-8")
        assert _resolve_keywords_path(None, tmp_path / "config.toml") == sibling

    def test_falls_back_to_project_root(self, tmp_path: Path) -> None:
        result = _resolve_keywords_path(None, tmp_path / "config.toml")
        assert (
            result == main_module._resolve_project_root() / "config" / "keywords.toml"
        )

    def test_shipped_keywords_file_loads(self) -> None:
        """The repository ships a valid config/keywords.toml (Goal 1.4)."""
        repo_keywords = Path(__file__).resolve().parents[1] / "config" / "keywords.toml"
        assert repo_keywords.is_file()
        assert KeywordConfig.load(repo_keywords).general_ai.include


class TestResolveOutputDir:
    def test_explicit_path(self, tmp_path: Path) -> None:
        assert _resolve_output_dir(tmp_path / "out") == (tmp_path / "out").resolve()

    def test_default_is_data_digests(self) -> None:
        result = _resolve_output_dir(None)
        assert result.name == "digests"
        assert result.parent.name == "data"


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
# Log isolation (regression: tests must not dirty the committed logs/)
# --------------------------------------------------------------------------- #


def _repo_log_snapshot() -> dict[str, tuple[int, int]]:
    """Size + mtime of every file in the repo's real ``logs/`` directory."""
    logs_dir = Path(__file__).resolve().parents[1] / "logs"
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(logs_dir.glob("*"))
        if path.is_file()
    }


class TestLogIsolation:
    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_cli_run_leaves_repo_logs_untouched(
        self, mock_fetch: AsyncMock, tmp_path: Path, isolated_logging: Path
    ) -> None:
        """A CLI run logs into the resolved project root, never the repo's."""
        mock_fetch.return_value = []
        before = _repo_log_snapshot()

        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        result = runner.invoke(app, ["--config", str(config_file)])

        assert result.exit_code == 0
        assert _repo_log_snapshot() == before

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_cli_run_still_writes_audit_log(
        self, mock_fetch: AsyncMock, tmp_path: Path, isolated_logging: Path
    ) -> None:
        """Logging is redirected, not disabled — the temp audit log is written."""
        mock_fetch.return_value = []
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)

        result = runner.invoke(app, ["--config", str(config_file)])

        assert result.exit_code == 0
        audit_log = isolated_logging / "logs" / "audit.log"
        assert audit_log.is_file()
        assert "Loaded 1 sources" in audit_log.read_text(encoding="utf-8")

    def test_project_root_is_redirected(self, isolated_logging: Path) -> None:
        """The autouse fixture points the CLI at a throwaway project root.

        Looked up through the module (not a ``from ... import`` alias) because
        that is how ``collect()`` resolves it at call time, and therefore what
        ``monkeypatch.setattr`` redirects.
        """
        assert main_module._resolve_project_root() == isolated_logging
        assert isolated_logging != Path(__file__).resolve().parents[1]


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

    def test_invalid_config_exits_1(self, tmp_path: Path) -> None:
        """Malformed TOML is reported and exits 1."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("user_agent = \n[[[\n", encoding="utf-8")

        result = runner.invoke(app, ["--config", str(config_file)])
        assert result.exit_code == 1

    def test_missing_keywords_exits_1(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)

        result = runner.invoke(
            app,
            ["--config", str(config_file), "--keywords", str(tmp_path / "nope.toml")],
        )
        assert result.exit_code == 1

    def test_invalid_keywords_exits_1(self, tmp_path: Path) -> None:
        """A keyword file missing a bucket is a hard error, not a silent no-op."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        keywords_file = tmp_path / "broken-keywords.toml"
        keywords_file.write_text('[general_ai]\ninclude = ["AI"]\n', encoding="utf-8")

        result = runner.invoke(
            app,
            ["--config", str(config_file), "--keywords", str(keywords_file)],
        )
        assert result.exit_code == 1

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_collect_writes_candidates_artifact(
        self, mock_fetch: AsyncMock, tmp_path: Path
    ) -> None:
        """End to end: mocked fetch → scored candidate → v1-shaped JSON."""
        source = Source(
            name="Test Feed",
            scrape_url="https://example.com/feed",
            priority="high",
            fetch_type="rss",
            category="general_ai",
        )
        record = RawRecord(
            source=source,
            title="OpenAI releases a new foundation model",
            url="https://example.com/model?utm_source=rss",
            description="The company says the LLM agent beats every benchmark.",
        )
        mock_fetch.return_value = [FetchSuccess(source=source, records=[record])]

        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        out_dir = tmp_path / "digests"

        result = runner.invoke(
            app,
            [
                "--config",
                str(config_file),
                "--date",
                "2026-09-01",
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(
            (out_dir / "2026-09-01-candidates.json").read_text(encoding="utf-8")
        )
        assert payload["run_log"]["fetched_count"] == 1
        assert payload["run_log"]["filtered_count"] == 1
        assert payload["run_log"]["source_count"] == 1
        assert len(payload["top_10_general_ai"]) == 1

        item = payload["top_10_general_ai"][0]
        assert item["url"] == "https://example.com/model"
        assert item["source"] == "Test Feed"
        assert item["source_kind"] == "rss"
        assert item["score"] > 0
        assert "OpenAI" in item["matched_terms"]
        assert len(item["id"]) == 16

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_dry_run_writes_no_artifact(
        self, mock_fetch: AsyncMock, tmp_path: Path
    ) -> None:
        mock_fetch.return_value = []
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)
        out_dir = tmp_path / "digests"

        result = runner.invoke(
            app,
            [
                "--config",
                str(config_file),
                "--dry-run",
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0
        assert not out_dir.exists()

    @patch("newsletter.main.fetch_all_sources", new_callable=AsyncMock)
    def test_sibling_keywords_file_is_used(
        self, mock_fetch: AsyncMock, tmp_path: Path
    ) -> None:
        """A self-contained config directory can ship its own buckets."""
        source = Source(
            name="Test Feed",
            scrape_url="https://example.com/feed",
            priority="high",
            fetch_type="rss",
            category="general_ai",
        )
        record = RawRecord(
            source=source,
            title="Zorblax ships a widget",
            url="https://example.com/zorblax",
            description="The zorblax widget handles flux capacity today.",
        )
        mock_fetch.return_value = [FetchSuccess(source=source, records=[record])]

        (tmp_path / "config.toml").write_text(_MINIMAL_CONFIG)
        (tmp_path / "keywords.toml").write_text(
            '[general_ai]\ninclude = ["zorblax"]\n\n'
            '[engineering_ai]\ninclude = ["cae"]\n',
            encoding="utf-8",
        )
        out_dir = tmp_path / "digests"

        result = runner.invoke(
            app,
            [
                "--config",
                str(tmp_path / "config.toml"),
                "--date",
                "2026-09-01",
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(
            (out_dir / "2026-09-01-candidates.json").read_text(encoding="utf-8")
        )
        assert payload["top_10_general_ai"][0]["matched_terms"] == ["zorblax"]

    def test_cancellation_exits_130(self, tmp_path: Path) -> None:
        """Ctrl-C during the fetch stage maps onto exit code 130."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(_MINIMAL_CONFIG)

        def cancel(coro: Coroutine[Any, Any, Any]) -> None:
            coro.close()  # otherwise CPython warns "coroutine was never awaited"
            raise asyncio.CancelledError

        with patch("newsletter.main.asyncio.run", side_effect=cancel):
            result = runner.invoke(app, ["--config", str(config_file)])

        assert result.exit_code == 130


# --------------------------------------------------------------------------- #
# Signal handling and entry point
# --------------------------------------------------------------------------- #


class TestSignalHandling:
    async def test_without_a_current_task_it_is_a_noop(self) -> None:
        """From a bare loop callback there is no task to cancel.

        ``asyncio.current_task()`` needs a *running* loop, so the early
        return is exercised from ``call_soon`` — a callback context where
        no task is executing.
        """
        loop = asyncio.get_running_loop()
        finished = asyncio.Event()

        def install() -> None:
            try:
                _install_signal_handlers(loop)
            finally:
                finished.set()

        loop.call_soon(install)
        await asyncio.wait_for(finished.wait(), timeout=1.0)
        assert finished.is_set()

    async def test_cancelled_pipeline_returns_130(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
    ) -> None:
        """When the pipeline task is cancelled, exit code is 130."""

        async def slow_fetch(
            sources: list,
            client: httpx.AsyncClient,
            **kwargs: object,
        ) -> list:
            await asyncio.sleep(60)
            return []

        config = make_configuration(
            sources=[
                Source(
                    name="Slow",
                    scrape_url="https://slow.com/feed",
                    priority="high",
                    fetch_type="rss",
                    category="general_ai",
                )
            ],
            user_agent="test/1.0",
        )

        async def run_and_cancel() -> int:
            task = asyncio.current_task()
            assert task is not None  # always set inside a running coroutine

            # Schedule cancellation after a short delay.
            async def cancel_soon() -> None:
                await asyncio.sleep(0.05)
                task.cancel()

            asyncio.ensure_future(cancel_soon())

            try:
                with patch(
                    "newsletter.main.fetch_all_sources",
                    new_callable=AsyncMock,
                    side_effect=slow_fetch,
                ):
                    async with httpx.AsyncClient() as client:
                        await collect_candidates(
                            client, config, keyword_config, now=NOW
                        )
                return 0
            except asyncio.CancelledError:
                return 130

        exit_code = await run_and_cancel()
        assert exit_code == 130


class TestEntryPoint:
    def test_main_invokes_the_typer_app(self) -> None:
        """``[project.scripts] newsletter = newsletter.main:main``."""
        with patch.object(main_module, "app") as mock_app:
            main_module.main()
        mock_app.assert_called_once_with()
