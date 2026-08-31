"""Fetcher registry and source-type dispatch.

Maps ``fetch_type`` strings to :class:`~newsletter.fetchers.base.Fetcher`
implementations.  The orchestration layer calls :func:`get_fetcher` to
resolve the right fetcher for a given :class:`~newsletter.models.Source`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from newsletter.models import Source

from .base import Fetcher
from .rss import RSSFetcher

__all__ = [
    "FETCHER_REGISTRY",
    "Fetcher",
    "RSSFetcher",
    "fetch_kind",
    "get_fetcher",
]

# --------------------------------------------------------------------------- #
# Registry — populated at import time with all known fetcher implementations.
# --------------------------------------------------------------------------- #

_rss_fetcher = RSSFetcher()

FETCHER_REGISTRY: dict[str, Fetcher] = {
    ft: _rss_fetcher for ft in _rss_fetcher.fetch_types
}
# When new fetchers are added, register them here:
#   from .hn import HNFetcher
#   _hn = HNFetcher()
#   FETCHER_REGISTRY.update({ft: _hn for ft in _hn.fetch_types})


# --------------------------------------------------------------------------- #
# Fetch-kind resolution
# --------------------------------------------------------------------------- #


def fetch_kind(source: Source) -> str:
    """Resolve the effective fetch strategy for a source.

    Mirrors the v1 ``fetch_kind`` logic:

    1. If ``fetch_type`` is explicitly set, use it.
    2. Else infer from ``source_type`` (``rss`` → ``"rss"``,
       ``website`` → ``"sitemap_or_search"``, etc.).
    3. Fall back to ``"web_search_query"``.
    """
    if source.fetch_type:
        return source.fetch_type

    st = source.source_type
    if st == "rss":
        return "rss"
    if st == "website":
        return "sitemap_or_search"
    if st in {"manual", "newsletter", "linkedin_manual", "x_api", "github", "arxiv"}:
        return "web_search_query"

    return st or "web_search_query"


def auto_query(source: Source) -> str:
    """Generate a default search query from a source's URL.

    Used for ``web_search_query`` and ``sitemap_or_search`` sources that
    don't declare an explicit ``query`` field.
    """
    netloc = urlsplit(source.scrape_url).netloc
    return f"site:{netloc} AI"


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


class UnknownFetcherError(Exception):
    """Raised when no fetcher is registered for a given fetch type."""


def get_fetcher(source: Source) -> Fetcher:
    """Return the registered fetcher for *source*'s resolved fetch kind.

    Raises :class:`UnknownFetcherError` if no implementation is registered
    for the resolved fetch type.
    """
    kind = fetch_kind(source)
    try:
        return FETCHER_REGISTRY[kind]
    except KeyError:
        raise UnknownFetcherError(
            f"No fetcher registered for fetch_type={kind!r} (source={source.name!r})"
        ) from None
