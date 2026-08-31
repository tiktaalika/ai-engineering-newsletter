"""Pipeline entry point — fetch, score, deduplicate, select."""

from __future__ import annotations

import email.utils
import logging
import logging.config
import sys
from datetime import UTC, datetime
from pathlib import Path
from tomllib import load as load_toml
from typing import Any

import httpx
from rss_parser import parse as parse_rss

from .configuration import Configuration
from .models import (
    Candidate,
    RawRecord,
    ScoreBreakdown,
    Source,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_pub_date(raw_date: Any) -> datetime | None:
    """Best-effort datetime parsing with multi-format fallback.

    Returns ``None`` when parsing fails so callers can handle missing
    publication dates explicitly.
    """
    if isinstance(raw_date, datetime):
        if raw_date.tzinfo is None:
            return raw_date.replace(tzinfo=UTC)
        return raw_date
    if not isinstance(raw_date, str):
        return None

    val = raw_date.strip()
    if not val:
        return None

    try:
        dt = email.utils.parsedate_to_datetime(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError, TypeError:
        pass

    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError, TypeError:
        logger.debug("Unparseable date value: %r", val)

    return None


# --------------------------------------------------------------------------- #
# RSS fetching (sync — will become async in Goal 3)
# --------------------------------------------------------------------------- #


def fetch_rss_records(source: Source, client: httpx.Client) -> list[RawRecord]:
    """Fetch and parse an RSS/Atom feed into raw records."""
    assert source.fetch_type in {"rss", "atom", "rdf"}, (
        f"fetch_rss_records called with fetch_type={source.fetch_type!r}"
    )

    response = client.get(source.scrape_url)
    response.raise_for_status()

    feed = parse_rss(response.content)
    records: list[RawRecord] = []

    channel = getattr(feed, "channel", None)
    items = getattr(channel, "items", []) or [] if channel else []

    for item in items:
        title = _extract_title(item)
        link = _extract_link(item, source.scrape_url)
        description = _extract_description(item)
        pub_date = _extract_pub_date(item)

        records.append(
            RawRecord(
                source=source,
                title=title,
                url=link,
                description=description,
                pub_date=pub_date,
            )
        )

    return records


def _extract_title(item: Any) -> str:
    if not (hasattr(item, "title") and item.title is not None):
        return ""
    title_val = item.title.content if hasattr(item.title, "content") else item.title
    return str(title_val).strip() if title_val is not None else ""


def _extract_link(item: Any, fallback_url: str) -> str:
    links = getattr(item, "links", []) or []
    for link in links:
        l_content = getattr(link, "content", None)
        l_attrs = getattr(link, "attributes", {}) or {}
        if l_content:
            href = str(l_content).strip()
            if href:
                return href
        if l_attrs.get("href"):
            href = str(l_attrs["href"]).strip()
            if href:
                return href
    if hasattr(item, "link") and item.link is not None:
        link_val = item.link.content if hasattr(item.link, "content") else item.link
        if link_val is not None:
            href = str(link_val).strip()
            if href:
                return href
    return fallback_url


def _extract_description(item: Any) -> str:
    if not (hasattr(item, "description") and item.description is not None):
        return ""
    desc_val = (
        item.description.content
        if hasattr(item.description, "content")
        else item.description
    )
    return str(desc_val).strip() if desc_val is not None else ""


def _extract_pub_date(item: Any) -> datetime | None:
    raw_date = None
    if hasattr(item, "pub_date"):
        pd = item.pub_date
        raw_date = pd.content if hasattr(pd, "content") else pd
    return _parse_pub_date(raw_date)


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

    Currently handles only RSS-family fetch types. Other types are
    logged and skipped until the async fetcher system (Goal 3–4) lands.
    """
    all_candidates: list[Candidate] = []

    for src in config.sources:
        if not src.enabled:
            logger.debug("Skipping disabled source: %s", src.name)
            continue

        if src.fetch_type in {"rss", "atom", "rdf"}:
            try:
                records = fetch_rss_records(src, request_client)
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
        else:
            logger.debug(
                "Skipping source with unimplemented fetch_type %r: %s",
                src.fetch_type,
                src.name,
            )

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
