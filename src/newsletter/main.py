import email.utils
import logging
import logging.config
import sys
from datetime import UTC, datetime
from pathlib import Path
from tomllib import load as load_toml
from typing import Any

import httpx
from attrs import field, frozen
from rss_parser import parse as parse_rss

from .configuration import Configuration, Source

logger = logging.getLogger("collect_candidates")


def _parse_pub_date(raw_date: Any) -> datetime:
    if isinstance(raw_date, datetime):
        if raw_date.tzinfo is None:
            return raw_date.replace(tzinfo=UTC)
        return raw_date
    if isinstance(raw_date, str):
        val = raw_date.strip()
        try:
            dt = email.utils.parsedate_to_datetime(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError) as e:
            logger.info(f"{e}")
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError) as e:
            logger.info(f"{e}")

    return datetime.now(tz=UTC)


@frozen
class RawRSSRecord:
    source_name: str
    title: str
    link: str
    description: str
    pub_date: datetime
    engagement: dict[str, float | int | None] = field(factory=dict)


def fetch_rss_record(source: Source, client: httpx.Client) -> list[RawRSSRecord]:
    """Fetch and parse rss fetched records."""
    assert source.fetch_type == "rss"

    response = client.get(source.scrape_url)
    response.raise_for_status()

    feed = parse_rss(response.content)
    records: list[RawRSSRecord] = []

    channel = getattr(feed, "channel", None)
    items = getattr(channel, "items", []) or [] if channel else []

    for item in items:
        title = ""
        if hasattr(item, "title") and item.title is not None:
            title_val = (
                item.title.content if hasattr(item.title, "content") else item.title
            )
            if title_val is not None:
                title = str(title_val).strip()

        link = ""
        links = getattr(item, "links", []) or []
        for l in links:
            l_content = getattr(l, "content", None)
            l_attrs = getattr(l, "attributes", {}) or {}
            if l_content:
                link = str(l_content).strip()
                break
            if l_attrs.get("href"):
                link = str(l_attrs["href"]).strip()
                break
        if not link and hasattr(item, "link") and item.link is not None:
            link_val = item.link.content if hasattr(item.link, "content") else item.link
            if link_val is not None:
                link = str(link_val).strip()
        if not link:
            link = source.scrape_url

        description = ""
        if hasattr(item, "description") and item.description is not None:
            desc_val = (
                item.description.content
                if hasattr(item.description, "content")
                else item.description
            )
            if desc_val is not None:
                description = str(desc_val).strip()

        raw_date = (
            item.pub_date.content
            if hasattr(item, "pub_date") and hasattr(item.pub_date, "content")
            else getattr(item, "pub_date", None)
        )
        pub_date = _parse_pub_date(raw_date)

        records.append(
            RawRSSRecord(
                source_name=source.name,
                title=title,
                link=link,
                description=description,
                pub_date=pub_date,
            )
        )

    return records


def rss_record_to_canidate(source: Source, record: RawRSSRecord) -> Candidate:
    """Convert RSS record to candiate"""
    return Candidate(
        title=record.title,
        description=record.description,
        pub_date=record.pub_date,
        url=record.link,
        source=source,
    )


@frozen
class Candidate:
    title: str
    description: str
    url: str
    pub_date: datetime
    source: Source


def fetch_sources(request_client: httpx.Client, config: Configuration):
    all_candidates: list[Candidate] = []
    for src in config.sources:
        if src.fetch_type == "rss":
            records = fetch_rss_record(src, request_client)
            all_candidates.extend(
                [rss_record_to_canidate(src, record) for record in records]
            )

    return all_candidates


def main() -> int:
    config_directory = Path(__file__).resolve().parent.parent.parent / "config"

    with (config_directory / "logging.toml").open("rb") as f:
        logging.config.dictConfig(load_toml(f))

    config = Configuration.load(config_directory / "config.toml")

    print(config.priority_presets)
    print(config.category_window_hours)
    print(config.sources)
    print(config.user_agent)

    request_client = httpx.Client(
        headers={"User-Agent": config.user_agent},
        timeout=12.0,
        follow_redirects=True,
    )

    fetch_sources(request_client, config)

    return 0


if __name__ == "__main__":
    sys.exit(main())
