"""RSS / Atom / RDF feed fetcher.

Parses all XML feed dialects with the stdlib ``xml.etree.ElementTree``
API wrapped by ``defusedxml``, which blocks entity-expansion bombs,
external entity (XXE) resolution, and DTD abuse.

Lenient by design: real-world feeds routinely omit optional fields, so
missing fields degrade to defaults instead of failing the whole source.
Field resolution mirrors v1 ``parse_rss`` (1:1 replication spec):

- link:      ``<link>`` text → Atom ``<link href="...">`` attribute → ``""``
- summary:   ``description`` → ``summary`` → ``content`` → ``content:encoded``
- published: ``pubDate`` → ``dc:date`` → ``published`` → ``updated``
"""

from __future__ import annotations

import email.utils
import logging
import re
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as parse_xml_safe

from newsletter.http import fetch_bytes
from newsletter.models import RawRecord, Source

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Per-source record cap when ``Source.max_entries`` is not set (v1 parity).
DEFAULT_MAX_ENTRIES: int = 25

#: Guard against absurdly large feed bodies (memory safety).
MAX_FEED_BYTES: int = 10 * 1024 * 1024

#: Local element names that mark a feed entry in any dialect.
_ITEM_LOCAL_NAMES: frozenset[str] = frozenset({"item", "entry"})

# XML entity cleanup — fix bare ``&`` that isn't already a valid entity ref.
# NOTE: the str and bytes patterns must stay in sync.
_ENTITY_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")
_ENTITY_RE_BYTES = re.compile(rb"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


class FeedParseError(Exception):
    """Raised when a feed body cannot be parsed as XML.

    Also raised for XML rejected by ``defusedxml`` (entity bombs, XXE,
    hostile DTDs) so hostile feeds surface as ordinary fetch failures.
    """


# --------------------------------------------------------------------------- #
# XML cleanup
# --------------------------------------------------------------------------- #


def _clean_xml_entities(raw: str) -> str:
    """Replace bare ``&`` characters that would break XML parsing."""
    return _ENTITY_RE.sub("&amp;", raw)


def _clean_xml_bytes(raw: bytes) -> bytes:
    """Byte-level twin of :func:`_clean_xml_entities`.

    Operates on bytes so the XML parser can honour the encoding declared
    in the XML prolog (feeds are frequently not UTF-8).
    """
    return _ENTITY_RE_BYTES.sub(b"&amp;", raw)


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
# Element helpers (namespace-tolerant via local-name matching)
# --------------------------------------------------------------------------- #


def _local_name(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an element tag."""
    return tag.rsplit("}", 1)[-1]


def _find_items(root: ET.Element) -> list[ET.Element]:
    """Find all ``<item>`` / ``<entry>`` elements in any namespace.

    Local-name matching handles RSS 2.0 (``item``), RDF/RSS 1.0
    (``{http://purl.org/rss/1.0/}item``), and Atom (``{...Atom}entry``)
    with a single mechanism, and tolerates unusual namespace prefixes.
    """
    return [
        el
        for el in root.iter()
        if isinstance(el.tag, str) and _local_name(el.tag) in _ITEM_LOCAL_NAMES
    ]


def _first_child(item: ET.Element, name: str) -> ET.Element | None:
    """First direct child of *item* whose local name equals *name*."""
    for child in item:
        if isinstance(child.tag, str) and _local_name(child.tag) == name:
            return child
    return None


def _children_named(item: ET.Element, name: str) -> list[ET.Element]:
    """All direct children of *item* whose local name equals *name*."""
    return [
        child
        for child in item
        if isinstance(child.tag, str) and _local_name(child.tag) == name
    ]


def _text_of(el: ET.Element | None) -> str:
    """Concatenated, stripped text content of *el* (CDATA-transparent)."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


# --------------------------------------------------------------------------- #
# Item field extraction
# --------------------------------------------------------------------------- #


def _extract_link(item: ET.Element) -> str:
    """Resolve the article URL.

    Order: ``<link>`` element text (RSS/RDF) → Atom ``<link href>``
    attribute (preferring ``rel="alternate"`` or absent ``rel``) → ``""``.
    An empty string lets downstream ``entry_id()`` fall back to the title
    (v1 semantics) instead of collapsing items onto the feed URL.
    """
    for el in _children_named(item, "link"):
        text = _text_of(el)
        if text:
            return text

    # Atom-style links: href attribute on one or more <link> elements.
    fallback: str = ""
    for el in _children_named(item, "link"):
        href = str(el.attrib.get("href", "")).strip()
        if not href:
            continue
        rel = el.attrib.get("rel", "alternate")
        if rel == "alternate":
            return href
        if not fallback:
            fallback = href
    return fallback


def _extract_description(item: ET.Element) -> str:
    """First non-empty of description / summary / content / encoded."""
    for name in ("description", "summary", "content", "encoded"):
        text = _text_of(_first_child(item, name))
        if text:
            return text
    return ""


def _extract_pub_date(item: ET.Element) -> datetime | None:
    """First parseable of pubDate / dc:date / published / updated."""
    for name in ("pubDate", "date", "published", "updated"):
        dt = parse_pub_date(_text_of(_first_child(item, name)))
        if dt is not None:
            return dt
    return None


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
        raw_bytes = await fetch_bytes(client, source.scrape_url)

        if len(raw_bytes) > MAX_FEED_BYTES:
            raise FeedParseError(
                f"Feed body too large ({len(raw_bytes)} bytes > {MAX_FEED_BYTES}) "
                f"from source {source.name!r}"
            )

        # Clean bare ``&`` entities that break XML parsers.
        raw_bytes = _clean_xml_bytes(raw_bytes)

        try:
            root = parse_xml_safe(raw_bytes)
        except (ET.ParseError, DefusedXmlException) as exc:
            raise FeedParseError(
                f"Unparseable XML from source {source.name!r}: {type(exc).__name__}"
            ) from exc

        limit = (
            source.max_entries
            if source.max_entries is not None
            else DEFAULT_MAX_ENTRIES
        )

        records: list[RawRecord] = []
        for item in _find_items(root)[:limit]:
            records.append(
                RawRecord(
                    source=source,
                    title=_text_of(_first_child(item, "title")),
                    url=_extract_link(item),
                    description=_extract_description(item),
                    pub_date=_extract_pub_date(item),
                )
            )

        return records
