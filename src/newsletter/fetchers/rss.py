"""RSS / Atom / RDF feed fetcher.

Handles all feed-based sources by parsing XML via the ``rss_parser`` library.
Supports ``fetch_type`` values: ``rss``, ``atom``, ``rdf``.
"""

from __future__ import annotations

import email.utils
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from rss_parser import parse as parse_rss

from newsletter.http import fetch_text
from newsletter.models import RawRecord, Source

logger = logging.getLogger(__name__)

# XML entity cleanup — fix bare ``&`` that isn't already a valid entity ref.
_ENTITY_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def _clean_xml_entities(raw: str) -> str:
    """Replace bare ``&`` characters that would break XML parsing."""
    return _ENTITY_RE.sub("&amp;", raw)


# --------------------------------------------------------------------------- #
# Date parsing (shared utility — may be used by other fetchers)
# --------------------------------------------------------------------------- #


def parse_pub_date(raw_date: Any) -> datetime | None:
    """Best-effort datetime parsing with multi-format fallback.

    Handles RFC 2822 (RSS ``pubDate``), ISO 8601, and plain date strings.
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

    # RFC 2822 — standard RSS pubDate format
    try:
        dt = email.utils.parsedate_to_datetime(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError, TypeError:
        pass

    # ISO 8601 / plain date fallbacks
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError, TypeError:
        logger.debug("Unparseable date value: %r", val)

    return None


# --------------------------------------------------------------------------- #
# RSS item field extraction helpers
# --------------------------------------------------------------------------- #


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
    # RSS uses ``description``; Atom uses ``summary`` (or ``content``).
    for attr in ("description", "summary"):
        val = getattr(item, attr, None)
        if val is not None:
            inner = val.content if hasattr(val, "content") else val
            text = str(inner).strip() if inner is not None else ""
            if text:
                return text
    return ""


def _extract_pub_date(item: Any) -> datetime | None:
    # RSS uses ``pub_date``; Atom uses ``published`` (or ``updated``).
    for attr in ("pub_date", "published", "updated"):
        val = getattr(item, attr, None)
        if val is not None:
            raw = val.content if hasattr(val, "content") else val
            dt = parse_pub_date(raw)
            if dt is not None:
                return dt
    return None


def _extract_items(feed: Any) -> list[Any]:
    """Extract item/entry list from a parsed RSS or Atom feed.

    RSS feeds expose items via ``feed.channel.items``.
    Atom feeds expose entries via ``feed.feed.content.entries``.
    """
    # RSS path
    channel = getattr(feed, "channel", None)
    if channel is not None:
        items = getattr(channel, "items", []) or []
        return list(items)

    # Atom path
    atom_feed = getattr(feed, "feed", None)
    if atom_feed is not None:
        feed_content = getattr(atom_feed, "content", None)
        if feed_content is not None:
            entries = getattr(feed_content, "entries", []) or []
            return list(entries)

    return []


# --------------------------------------------------------------------------- #
# RSSFetcher
# --------------------------------------------------------------------------- #


class RSSFetcher:
    """Fetch and parse RSS 2.0, Atom, and RDF feeds into raw records."""

    _SUPPORTED_TYPES = frozenset({"rss", "atom", "rdf"})

    @property
    def fetch_types(self) -> frozenset[str]:
        return self._SUPPORTED_TYPES

    async def fetch(
        self,
        source: Source,
        client: httpx.AsyncClient,
        *,
        cutoff: datetime | None = None,
    ) -> list[RawRecord]:
        """Fetch an RSS/Atom/RDF feed and parse it into raw records."""
        raw_text = await fetch_text(client, source.scrape_url)

        # Clean bare ``&`` entities that break XML parsers.
        raw_text = _clean_xml_entities(raw_text)
        feed = parse_rss(raw_text)

        items = _extract_items(feed)

        records: list[RawRecord] = []
        for item in items:
            records.append(
                RawRecord(
                    source=source,
                    title=_extract_title(item),
                    url=_extract_link(item, source.scrape_url),
                    description=_extract_description(item),
                    pub_date=_extract_pub_date(item),
                )
            )

        return records
