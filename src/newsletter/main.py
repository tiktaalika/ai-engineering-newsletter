"""Pipeline entry point — fetch, score, deduplicate, select.

Provides a Typer CLI with the ``collect`` command that fetches all
enabled sources concurrently and produces scored candidates.

Usage::

    newsletter collect
    newsletter collect --config path/to/config.toml
    newsletter collect --window-hours 48 --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
from datetime import date
from pathlib import Path
from tomllib import load as load_toml
from typing import Annotated, Optional
from uuid import uuid4

import httpx
import typer

from .configuration import Configuration
from .models import (
    Candidate,
    FetchFailure,
    FetchSuccess,
    RawRecord,
    ScoreBreakdown,
    Source,
)
from .orchestrate import fetch_all_sources

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="newsletter",
    help="AI Engineering Newsletter pipeline.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


# --------------------------------------------------------------------------- #
# Record → Candidate conversion
# --------------------------------------------------------------------------- #


def raw_record_to_candidate(source: Source, record: RawRecord) -> Candidate:
    """Convert a raw fetched record into a scored candidate.

    Scoring and keyword matching are stubs here — the real logic lands
    in Goals 6.2–6.3. For now every record gets a zero score.
    """
    return Candidate(
        id=str(uuid4()),
        title=record.title,
        url=record.url,
        source=source,
        category=source.category,
        pub_date=record.pub_date,
        text=record.description,  # raw description → text (cleaned in Goal 6.1)
        description=record.description,
        engagement=record.engagement,
        score_breakdown=ScoreBreakdown(score=0.0),
        registry_category=source.category,
        source_priority=source.priority,
    )


# --------------------------------------------------------------------------- #
# Source orchestration
# --------------------------------------------------------------------------- #


async def collect_candidates(
    request_client: httpx.AsyncClient,
    config: Configuration,
) -> list[Candidate]:
    """Fetch all enabled sources concurrently and convert to candidates."""
    results = await fetch_all_sources(config.sources, request_client)

    candidates: list[Candidate] = []
    for result in results:
        if isinstance(result, FetchSuccess):
            candidates.extend(
                raw_record_to_candidate(result.source, record)
                for record in result.records
            )
        elif isinstance(result, FetchFailure):
            logger.warning(
                "Source %r failed (%.0f ms): %s",
                result.source.name,
                result.elapsed_ms,
                result.error,
            )

    return candidates


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
    *,
    window_hours: int,
    run_date: date,
    dry_run: bool,
) -> int:
    """Execute the full collect pipeline."""
    if not config.sources:
        logger.error("No sources defined in configuration")
        return 1

    logger.info(
        "Loaded %d sources (user_agent=%s, date=%s, window=%dh, dry_run=%s)",
        len(config.sources),
        config.user_agent,
        run_date.isoformat(),
        window_hours,
        dry_run,
    )

    _install_signal_handlers(asyncio.get_running_loop())

    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=15.0,
        follow_redirects=True,
    ) as request_client:
        candidates = await collect_candidates(request_client, config)

    logger.info("Collected %d total candidates", len(candidates))

    if dry_run:
        logger.info("Dry run — skipping output")
    # TODO: scoring, dedup, selection, output writing (Goals 6–7)

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
            help="Fetch sources but skip scoring and output.",
        ),
    ] = False,
) -> None:
    """Collect, score, deduplicate, and select newsletter candidates."""
    project_root = _resolve_project_root()
    _setup_logging(project_root)

    config_path = _resolve_config_path(config)

    try:
        cfg = Configuration.load(config_path)
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", config_path)
        raise typer.Exit(code=1) from None
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load configuration: %s", exc)
        raise typer.Exit(code=1) from None

    run_date = date.fromisoformat(date_str) if date_str else date.today()

    try:
        exit_code = asyncio.run(
            _run_pipeline(
                cfg,
                window_hours=window_hours,
                run_date=run_date,
                dry_run=dry_run,
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
