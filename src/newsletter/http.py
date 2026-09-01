"""Shared async HTTP utilities for the newsletter pipeline.

Provides retry-with-backoff, per-domain rate limiting, and thin async
wrappers around ``httpx.AsyncClient`` for text, JSON, and binary fetches.

Usage::

    async with httpx.AsyncClient(headers={"User-Agent": "..."}) as client:
        text = await fetch_text(client, "https://example.com/feed.xml")
        data = await fetch_json(client, "https://api.example.com/v1/items")
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_TIMEOUT: float = 15.0
DEFAULT_MAX_ATTEMPTS: int = 3
DEFAULT_MAX_REDIRECTS: int = 5
DEFAULT_REQUEST_DELAY: float = 0.0
DEFAULT_MAX_BACKOFF: float = 30.0

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 503})

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class FetchError(Exception):
    """Base exception for HTTP fetch failures."""

    url: str

    def __init__(self, message: str, url: str) -> None:
        self.url = url
        super().__init__(message)


class HTTPStatusFetchError(FetchError):
    """A non-retryable HTTP error status (4xx except 429)."""

    status_code: int

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} for {url}", url)


class MaxRetriesExceeded(FetchError):
    """All retry attempts were exhausted."""


# --------------------------------------------------------------------------- #
# Backoff helper
# --------------------------------------------------------------------------- #


def backoff_delay(
    attempt: int,
    base: float = 1.0,
    *,
    max_delay: float = DEFAULT_MAX_BACKOFF,
) -> float:
    """Exponential backoff delay with jitter (seconds).

    ``attempt`` is zero-indexed (0 = first retry).

    Returns ``min(base * 2^attempt, max_delay) + jitter``.
    Jitter is uniformly distributed in ``[0, base)``.
    """
    delay = min(base * (2**attempt), max_delay)
    jitter = random.uniform(0, base)  # noqa: S311
    return delay + jitter


# --------------------------------------------------------------------------- #
# Per-domain rate limiter
# --------------------------------------------------------------------------- #


class DomainRateLimiter:
    """Enforces a minimum delay between consecutive requests to the same host.

    Safe for concurrent use within a single asyncio event loop.  Each host
    is serialised: the second concurrent caller waits until the first
    caller's delay has elapsed before its own request is dispatched.

    Usage::

        limiter = DomainRateLimiter(delay_seconds=1.0)

        async with limiter.limit("https://example.com/a"):
            await client.get("https://example.com/a")

        async with limiter.limit("https://other.com/b"):
            await client.get("https://other.com/b")  # no delay — different host
    """

    def __init__(self, delay_seconds: float = DEFAULT_REQUEST_DELAY) -> None:
        self.delay_seconds = delay_seconds
        self._last_access: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def acquire(self, url: str) -> None:
        """Wait until the per-host delay has elapsed, then mark the host accessed.

        Call this *before* dispatching the HTTP request.
        """
        if self.delay_seconds <= 0:
            return

        host = urlsplit(url).netloc
        async with self._lock_for(host):
            now = asyncio.get_running_loop().time()
            last = self._last_access.get(host, 0.0)
            wait = self.delay_seconds - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_access[host] = asyncio.get_running_loop().time()


# --------------------------------------------------------------------------- #
# Core fetch with retry
# --------------------------------------------------------------------------- #


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    response_format: str = "text",
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    rate_limiter: DomainRateLimiter | None = None,
) -> str | bytes | dict[str, Any]:
    """Execute an HTTP GET with retry and exponential backoff.

    Retryable conditions:
      - ``httpx.TimeoutException``
      - ``httpx.ConnectError``
      - HTTP 429 (Too Many Requests)
      - HTTP 503 (Service Unavailable)

    Non-retryable:
      - Any other 4xx/5xx → :class:`HTTPStatusFetchError`
      - All retries exhausted → :class:`MaxRetriesExceeded`

    Parameters
    ----------
    client:
        A shared ``httpx.AsyncClient``.
    url:
        Target URL.
    response_format:
        One of ``"text"``, ``"bytes"``, ``"json"``.
    timeout:
        Per-attempt timeout in seconds.
    max_attempts:
        Total attempts (first try + retries).
    max_backoff:
        Cap on backoff delay in seconds (before jitter).
    rate_limiter:
        Optional :class:`DomainRateLimiter` to enforce per-host pacing.
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        # Enforce per-domain rate limit before each attempt.
        if rate_limiter is not None:
            await rate_limiter.acquire(url)

        try:
            response = await client.get(url, timeout=timeout)

            # Retryable server/rate-limit status codes.
            if response.status_code in _RETRYABLE_STATUS_CODES:
                logger.warning(
                    "Retryable HTTP %d for %s (attempt %d/%d)",
                    response.status_code,
                    url,
                    attempt + 1,
                    max_attempts,
                )
                last_exc = httpx.HTTPStatusError(
                    f"{response.status_code}",
                    request=response.request,
                    response=response,
                )
                if attempt < max_attempts - 1:
                    delay = backoff_delay(attempt, max_delay=max_backoff)
                    await asyncio.sleep(delay)
                continue

            # Non-retryable HTTP errors — raise immediately.
            if response.status_code >= 400:
                raise HTTPStatusFetchError(response.status_code, url)

            if response_format == "json":
                return response.json()
            if response_format == "bytes":
                return response.content
            return response.text

        except HTTPStatusFetchError:
            raise  # propagate non-retryable errors without retry

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            logger.warning(
                "Network error for %s: %s (attempt %d/%d)",
                url,
                exc,
                attempt + 1,
                max_attempts,
            )
            if attempt < max_attempts - 1:
                delay = backoff_delay(attempt, max_delay=max_backoff)
                await asyncio.sleep(delay)

    raise MaxRetriesExceeded(
        f"Failed to fetch {url} after {max_attempts} attempts: {last_exc}",
        url,
    ) from last_exc


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    rate_limiter: DomainRateLimiter | None = None,
) -> str:
    """Fetch a URL and return its body as a decoded string."""
    result = await _fetch(
        client,
        url,
        response_format="text",
        timeout=timeout,
        max_attempts=max_attempts,
        max_backoff=max_backoff,
        rate_limiter=rate_limiter,
    )
    return cast(str, result)


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    rate_limiter: DomainRateLimiter | None = None,
) -> dict[str, Any]:
    """Fetch a URL and return its body parsed as JSON."""
    result = await _fetch(
        client,
        url,
        response_format="json",
        timeout=timeout,
        max_attempts=max_attempts,
        max_backoff=max_backoff,
        rate_limiter=rate_limiter,
    )
    return cast(dict[str, Any], result)


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    rate_limiter: DomainRateLimiter | None = None,
) -> bytes:
    """Fetch a URL and return its body as raw bytes."""
    result = await _fetch(
        client,
        url,
        response_format="bytes",
        timeout=timeout,
        max_attempts=max_attempts,
        max_backoff=max_backoff,
        rate_limiter=rate_limiter,
    )
    return cast(bytes, result)
