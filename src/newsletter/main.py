"""Pipeline entry point — fetch, score, deduplicate, select.

Provides a Typer CLI with the ``collect`` command that fetches all enabled
sources concurrently, filters and scores the records, selects the digest
sections, and writes ``YYYY-MM-DD-candidates.json``.

Usage::

    newsletter collect
    newsletter collect --config path/to/config.toml
    newsletter collect --window-hours 48 --dry-run
    newsletter collect --output-dir /tmp/digests
"""

from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
from datetime import UTC, date, datetime
from pathlib import Path
from tomllib import load as load_toml
from typing import Annotated, Optional

import httpx
import typer

from .artifacts import candidates_path, load_history, write_candidates_json
from .configuration import Configuration
from .keywords import KeywordConfig, KeywordError
from .models import Candidate, RunLog
from .orchestrate import fetch_all_sources
from .pipeline import build_issue
from .pipeline import collect as collect_stage
from .selection import (
    ENGINEERING_AI_LOOKBACK_DAYS,
    GENERAL_AI_LOOKBACK_DAYS,
    MEDICAL_BIO_AI_LOOKBACK_DAYS,
    RESEARCH_LOOKBACK_DAYS,
)

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="newsletter",
    help="AI Engineering Newsletter pipeline.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


# --------------------------------------------------------------------------- #
# Source orchestration
# --------------------------------------------------------------------------- #


async def collect_candidates(
    request_client: httpx.AsyncClient,
    config: Configuration,
    keywords: KeywordConfig,
    *,
    now: datetime | None = None,
    window_hours: int = 24,
) -> tuple[list[Candidate], RunLog]:
    """Fetch every enabled source concurrently, then filter and score.

    Returns the score-sorted candidates together with the run log that
    ends up in the artifact.
    """
    results = await fetch_all_sources(config.sources, request_client)
    return collect_stage(
        results,
        config=config,
        keywords=keywords,
        now=now,
        default_window_hours=window_hours,
    )


def load_section_history(
    output_dir: Path, date_slug: str
) -> dict[str, list[Candidate]]:
    """Read previously published selections for each section's lookback."""
    return {
        "general_ai": load_history(
            output_dir, date_slug, "general_ai", GENERAL_AI_LOOKBACK_DAYS
        ),
        "engineering_ai": load_history(
            output_dir, date_slug, "engineering_ai", ENGINEERING_AI_LOOKBACK_DAYS
        ),
        "medical_bio_ai": load_history(
            output_dir, date_slug, "medical_bio_ai", MEDICAL_BIO_AI_LOOKBACK_DAYS
        ),
        "research": load_history(
            output_dir, date_slug, "research", RESEARCH_LOOKBACK_DAYS
        ),
    }


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #


def _setup_logging(project_root: Path) -> None:
    """Load ``logging.toml`` and configure the logging system."""
    config_directory = project_root / "config"
    logs_directory = project_root / "logs"
    logs_directory.mkdir(exist_ok=True)

    logging_toml = config_directory / "logging.toml"
    if not logging_toml.exists():
        logging.basicConfig(level=logging.INFO)
        return

    with logging_toml.open("rb") as f:
        log_config = load_toml(f)

    for handler in log_config.get("handlers", {}).values():
        filename = handler.get("filename")
        if filename and not Path(filename).is_absolute():
            handler["filename"] = str(project_root / filename)

    logging.config.dictConfig(log_config)


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


def _resolve_project_root() -> Path:
    """Return the project root (three levels above this file)."""
    return Path(__file__).resolve().parent.parent.parent


def _resolve_config_path(config: Path | None) -> Path:
    """Return the config path, defaulting to ``<project_root>/config/config.toml``."""
    if config is not None:
        return config.resolve()
    return _resolve_project_root() / "config" / "config.toml"


def _resolve_keywords_path(keywords: Path | None, config_path: Path) -> Path:
    """Return the keyword config path.

    Precedence: the explicit ``--keywords`` flag, then a ``keywords.toml``
    sitting next to the loaded config (so a self-contained config directory
    works), then the project's ``config/keywords.toml``.
    """
    if keywords is not None:
        return keywords.resolve()
    sibling = config_path.parent / "keywords.toml"
    if sibling.exists():
        return sibling
    return _resolve_project_root() / "config" / "keywords.toml"


def _resolve_output_dir(output_dir: Path | None) -> Path:
    """Return the digest artifact directory (default ``<root>/data/digests``)."""
    if output_dir is not None:
        return output_dir.resolve()
    return _resolve_project_root() / "data" / "digests"


# --------------------------------------------------------------------------- #
# Signal handling
# --------------------------------------------------------------------------- #


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Register SIGINT/SIGTERM handlers for graceful shutdown.

    On signal, the currently running task is cancelled, which propagates
    through ``asyncio.gather`` to cancel all in-flight fetches.

    Silently does nothing on platforms where ``add_signal_handler`` is
    unsupported (Windows).
    """
    current_task = asyncio.current_task()
    if current_task is None:
        return

    def _request_shutdown() -> None:
        logger.warning("Shutdown signal received — cancelling pending tasks")
        current_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler.
            pass


# --------------------------------------------------------------------------- #
# Async pipeline
# --------------------------------------------------------------------------- #


async def _run_pipeline(
    config: Configuration,
    keywords: KeywordConfig,
    *,
    window_hours: int,
    run_date: date,
    dry_run: bool,
    output_dir: Path,
) -> int:
    """Execute the full collect pipeline."""
    if not config.sources:
        logger.error("No sources defined in configuration")
        return 1

    date_slug = run_date.isoformat()
    logger.info(
        "Loaded %d sources (user_agent=%s, date=%s, window=%dh, dry_run=%s)",
        len(config.sources),
        config.user_agent,
        date_slug,
        window_hours,
        dry_run,
    )

    _install_signal_handlers(asyncio.get_running_loop())

    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=15.0,
        follow_redirects=True,
    ) as request_client:
        candidates, run_log = await collect_candidates(
            request_client,
            config,
            keywords,
            now=datetime.now(tz=UTC),
            window_hours=window_hours,
        )

    logger.info(
        "Collected %d candidates from %d records (%d duplicates, %d source failures)",
        len(candidates),
        run_log.fetched_count,
        run_log.duplicate_count,
        len(run_log.failures),
    )

    if dry_run:
        logger.info("Dry run — skipping selection and output")
        return 0

    history = load_section_history(output_dir, date_slug)
    issue = build_issue(candidates, run_log, history=history)
    artifact = write_candidates_json(issue, candidates_path(output_dir, date_slug))
    logger.info(
        "Selected general=%d engineering=%d biomedical=%d research=%d → %s",
        len(issue.top_10_general_ai),
        len(issue.top_5_engineering_ai),
        len(issue.top_5_medical_bio_ai),
        len(issue.research_radar),
        artifact,
    )

    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@app.command()
def collect(
    config: Annotated[
        Optional[Path],
        typer.Option(
            "--config",
            "-c",
            help="Path to config.toml (default: <project_root>/config/config.toml).",
            exists=False,
        ),
    ] = None,
    window_hours: Annotated[
        int,
        typer.Option(
            "--window-hours",
            "-w",
            help="Look-back window in hours for recency scoring.",
        ),
    ] = 24,
    date_str: Annotated[
        Optional[str],
        typer.Option(
            "--date",
            "-d",
            help="Override run date (YYYY-MM-DD). Defaults to today.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Fetch and score sources but skip selection and output.",
        ),
    ] = False,
    keywords: Annotated[
        Optional[Path],
        typer.Option(
            "--keywords",
            "-k",
            help="Path to keywords.toml (default: next to --config, else "
            "<project_root>/config/keywords.toml).",
            exists=False,
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory for *-candidates.json (default: "
            "<project_root>/data/digests).",
            exists=False,
        ),
    ] = None,
) -> None:
    """Collect, score, deduplicate, and select newsletter candidates."""
    project_root = _resolve_project_root()
    _setup_logging(project_root)

    config_path = _resolve_config_path(config)
    keywords_path = _resolve_keywords_path(keywords, config_path)
    digest_dir = _resolve_output_dir(output_dir)

    try:
        cfg = Configuration.load(config_path)
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", config_path)
        raise typer.Exit(code=1) from None
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load configuration: %s", exc)
        raise typer.Exit(code=1) from None

    try:
        keyword_config = KeywordConfig.load(keywords_path)
    except FileNotFoundError:
        logger.error("Keyword configuration file not found: %s", keywords_path)
        raise typer.Exit(code=1) from None
    except KeywordError as exc:
        logger.error("Failed to load keyword configuration: %s", exc)
        raise typer.Exit(code=1) from None

    run_date = date.fromisoformat(date_str) if date_str else date.today()

    try:
        exit_code = asyncio.run(
            _run_pipeline(
                cfg,
                keyword_config,
                window_hours=window_hours,
                run_date=run_date,
                dry_run=dry_run,
                output_dir=digest_dir,
            )
        )
    except asyncio.CancelledError:
        logger.warning("Pipeline cancelled")
        exit_code = 130

    raise typer.Exit(code=exit_code)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """CLI entry point (called by ``[project.scripts]``)."""
    app()


if __name__ == "__main__":
    main()
