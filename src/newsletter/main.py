"""Pipeline entry point — fetch, score, deduplicate, select."""

from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from tomllib import load as load_toml
from uuid import uuid4

import httpx

from .configuration import Configuration
from .fetchers import UnknownFetcherError, get_fetcher
from .models import (
    Candidate,
    RawRecord,
    ScoreBreakdown,
    Source,
)

logger = logging.getLogger(__name__)


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


def fetch_sources(
    request_client: httpx.Client,
    config: Configuration,
) -> list[Candidate]:
    """Iterate over enabled sources and collect candidates.

    Resolves the appropriate :class:`Fetcher` for each source via the
    fetcher registry.  Sources with unregistered fetch types are logged
    and skipped.
    """
    all_candidates: list[Candidate] = []

    for src in config.sources:
        if not src.enabled:
            logger.debug("Skipping disabled source: %s", src.name)
            continue

        try:
            fetcher = get_fetcher(src)
        except UnknownFetcherError:
            logger.debug(
                "No fetcher for source %r (fetch_type=%s)",
                src.name,
                src.fetch_type,
            )
            continue

        try:
            records = fetcher.fetch(src, request_client)
            logger.info(
                "Fetched %d records from %s (%s)",
                len(records),
                src.name,
                src.fetch_type,
            )
            all_candidates.extend(
                raw_record_to_candidate(src, record) for record in records
            )
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch source: %s", src.name)

    return all_candidates


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent.parent
    config_directory = project_root / "config"
    logs_directory = project_root / "logs"

    logs_directory.mkdir(exist_ok=True)

    with (config_directory / "logging.toml").open("rb") as f:
        log_config = load_toml(f)

    # Resolve relative log file paths to absolute paths under project root.
    for handler in log_config.get("handlers", {}).values():
        filename = handler.get("filename")
        if filename and not Path(filename).is_absolute():
            handler["filename"] = str(project_root / filename)

    logging.config.dictConfig(log_config)

    config = Configuration.load(config_directory / "config.toml")

    if not config.sources:
        logger.error("No sources defined in configuration")
        return 1

    logger.info(
        "Loaded %d sources (user_agent=%s)",
        len(config.sources),
        config.user_agent,
    )

    with httpx.Client(
        headers={"User-Agent": config.user_agent},
        timeout=3.0,
        follow_redirects=True,
    ) as request_client:
        candidates = fetch_sources(request_client, config)
        logger.info("Collected %d total candidates", len(candidates))

    return 0


if __name__ == "__main__":
    sys.exit(main())
