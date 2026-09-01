"""Concurrent source-fetch orchestration.

Runs all enabled sources through their registered fetchers concurrently,
with semaphore-based concurrency limiting and full fault isolation.

Usage::

    async with httpx.AsyncClient(headers={"User-Agent": "..."}) as client:
        results = await fetch_all_sources(config.sources, client)

    successes = [r for r in results if isinstance(r, FetchSuccess)]
    failures  = [r for r in results if isinstance(r, FetchFailure)]
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import httpx

from .fetchers import UnknownFetcherError, get_fetcher
from .models import (
    FetchFailure,
    FetchResult,
    FetchSuccess,
    Source,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

DEFAULT_CONCURRENCY: int = 10
DEFAULT_SOURCE_TIMEOUT: float = 15.0


# --------------------------------------------------------------------------- #
# Single-source fetch wrapper
# --------------------------------------------------------------------------- #


async def _fetch_single(
    source: Source,
    client: httpx.AsyncClient,
    *,
    semaphore: asyncio.Semaphore,
    cutoff: datetime | None = None,
    source_timeout: float = DEFAULT_SOURCE_TIMEOUT,
) -> FetchResult:
    """Fetch one source, returning a :class:`FetchResult`.

    All exceptions are caught so one source's failure cannot cancel
    sibling tasks inside :func:`asyncio.gather`.

    The *semaphore* caps the number of concurrent in-flight fetches.
    """
    # Resolve fetcher — unregistered types become FetchFailure immediately.
    try:
        fetcher = get_fetcher(source)
    except UnknownFetcherError as exc:
        logger.debug("No fetcher for %r: %s", source.name, exc)
        return FetchFailure(source=source, error=str(exc), elapsed_ms=0.0)

    async with semaphore:
        t0 = time.monotonic()
        try:
            records = await asyncio.wait_for(
                fetcher.fetch(source, client, cutoff=cutoff),
                timeout=source_timeout,
            )
            elapsed = (time.monotonic() - t0) * 1000
            logger.info(
                "Fetched %d records from %s in %.0f ms",
                len(records),
                source.name,
                elapsed,
            )
            return FetchSuccess(source=source, records=records, elapsed_ms=elapsed)
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - t0) * 1000
            msg = f"Timed out after {source_timeout}s"
            logger.warning("Source %s: %s", source.name, msg)
            return FetchFailure(source=source, error=msg, elapsed_ms=elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.monotonic() - t0) * 1000
            msg = f"{type(exc).__name__}: {exc}"
            logger.warning("Source %s failed (%.0f ms): %s", source.name, elapsed, msg)
            return FetchFailure(source=source, error=msg, elapsed_ms=elapsed)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def fetch_all_sources(
    sources: list[Source],
    client: httpx.AsyncClient,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    cutoff: datetime | None = None,
    source_timeout: float = DEFAULT_SOURCE_TIMEOUT,
) -> list[FetchResult]:
    """Fetch all enabled sources concurrently.

    Disabled sources are silently skipped (not included in results).

    Parameters
    ----------
    sources:
        Full source list from configuration (enabled and disabled).
    client:
        A shared ``httpx.AsyncClient``.
    concurrency:
        Maximum number of simultaneous in-flight fetches.
    cutoff:
        Optional cutoff datetime forwarded to fetchers that support it.
    source_timeout:
        Per-source wall-clock timeout in seconds.

    Returns
    -------
    list[FetchResult]:
        One :class:`FetchSuccess` or :class:`FetchFailure` per enabled
        source, in the same order as the input.
    """
    enabled = [s for s in sources if s.enabled]
    if not enabled:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    tasks = [
        _fetch_single(
            source,
            client,
            semaphore=semaphore,
            cutoff=cutoff,
            source_timeout=source_timeout,
        )
        for source in enabled
    ]

    results: list[FetchResult] = list(await asyncio.gather(*tasks))

    n_ok = sum(1 for r in results if isinstance(r, FetchSuccess))
    n_fail = len(results) - n_ok
    logger.info(
        "Fetch complete: %d/%d succeeded, %d failed",
        n_ok,
        len(results),
        n_fail,
    )

    return results
