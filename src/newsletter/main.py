"""Pipeline entry point — fetch, score, deduplicate, select."""

from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from tomllib import load as load_toml

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
        id="",  # assigned by entry_id() in scoring module (Goal 6.1)
        title=record.title,
        url=record.url,
        source=source,
        category=source.category,
        pub_date=record.pub_date,
        text=record.description,  # raw description → text (cleaned in Goal 6.1)
        description=record.description,
        engagement=record.engagement,
        score_breakdown=ScoreBreakdown(score=0.0),
        source_tags=list(source.tags),
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
        except Exception:
            logger.exception("Failed to fetch source: %s", src.name)

    return all_candidates


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    config_directory = Path(__file__).resolve().parent.parent.parent / "config"

    if not Path("./logs").exists():
        Path("./logs").mkdir()

    with (config_directory / "logging.toml").open("rb") as f:
        logging.config.dictConfig(load_toml(f))

    config = Configuration.load(config_directory / "config.toml")

    if not config.sources:
        logger.error("No sources defined in configuration")
        return 1

    logger.info(
        "Loaded %d sources (user_agent=%s)",
        len(config.sources),
        config.user_agent,
    )

    request_client = httpx.Client(
        headers={"User-Agent": config.user_agent},
        timeout=12.0,
        follow_redirects=True,
    )

    candidates = fetch_sources(request_client, config)
    logger.info("Collected %d total candidates", len(candidates))

    return 0


if __name__ == "__main__":
    sys.exit(main())
