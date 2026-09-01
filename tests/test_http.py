"""Tests for the shared async HTTP utilities (newsletter.http)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from newsletter.http import (
    DomainRateLimiter,
    HTTPStatusFetchError,
    MaxRetriesExceeded,
    backoff_delay,
    fetch_bytes,
    fetch_json,
    fetch_text,
)

# --------------------------------------------------------------------------- #
# backoff_delay
# --------------------------------------------------------------------------- #


class TestBackoffDelay:
    def test_first_retry_base_range(self) -> None:
        """attempt=0 → delay in [1.0, 2.0) (base + jitter)."""
        for _ in range(50):
            d = backoff_delay(0, base=1.0, max_delay=30.0)
            assert 1.0 <= d < 2.0

    def test_exponential_growth(self) -> None:
        """Each successive attempt roughly doubles the base delay."""
        # Use max_delay large enough so the cap doesn't bite.
        d0 = backoff_delay(0, base=1.0, max_delay=100.0)
        d2 = backoff_delay(2, base=1.0, max_delay=100.0)
        # attempt=0 base is 1, attempt=2 base is 4 — at least 2x larger.
        assert d2 > d0 * 1.5

    def test_respects_max_delay_cap(self) -> None:
        """Delay never exceeds max_delay + jitter."""
        for _ in range(30):
            d = backoff_delay(10, base=1.0, max_delay=5.0)
            # base * 2^10 = 1024, capped to 5.0; jitter in [0, 1.0)
            assert d < 6.0

    def test_zero_base(self) -> None:
        """base=0 → always returns 0 (no delay)."""
        assert backoff_delay(0, base=0.0) == 0.0
        assert backoff_delay(5, base=0.0) == 0.0


# --------------------------------------------------------------------------- #
# fetch_text
# --------------------------------------------------------------------------- #


class TestFetchText:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://example.com/feed.xml").mock(
            return_value=httpx.Response(200, text="<rss>hello</rss>")
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_text(client, "https://example.com/feed.xml")

        assert result == "<rss>hello</rss>"

    @respx.mock
    async def test_404_raises_immediately(self) -> None:
        route = respx.get("https://example.com/missing").mock(
            return_value=httpx.Response(404, text="not found")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPStatusFetchError) as exc_info:
                await fetch_text(
                    client,
                    "https://example.com/missing",
                    max_attempts=3,
                    max_backoff=0.01,
                )

        assert exc_info.value.status_code == 404
        # 404 is non-retryable — only one attempt should be made.
        assert route.call_count == 1

    @respx.mock
    async def test_400_raises_immediately(self) -> None:
        route = respx.get("https://example.com/bad").mock(
            return_value=httpx.Response(400, text="bad request")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPStatusFetchError) as exc_info:
                await fetch_text(
                    client,
                    "https://example.com/bad",
                    max_attempts=3,
                    max_backoff=0.01,
                )

        assert exc_info.value.status_code == 400
        assert route.call_count == 1


# --------------------------------------------------------------------------- #
# fetch_json
# --------------------------------------------------------------------------- #


class TestFetchJson:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://api.example.com/items").mock(
            return_value=httpx.Response(200, json={"items": [1, 2, 3], "total": 3})
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_json(client, "https://api.example.com/items")

        assert result == {"items": [1, 2, 3], "total": 3}


# --------------------------------------------------------------------------- #
# fetch_bytes
# --------------------------------------------------------------------------- #


class TestFetchBytes:
    @respx.mock
    async def test_success(self) -> None:
        payload = b"\x89PNG\r\n\x1a\nbinary data here"
        respx.get("https://example.com/image.png").mock(
            return_value=httpx.Response(200, content=payload)
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_bytes(client, "https://example.com/image.png")

        assert result == payload


# --------------------------------------------------------------------------- #
# Retry behaviour
# --------------------------------------------------------------------------- #


class TestRetry:
    @respx.mock
    async def test_retry_on_429_then_success(self) -> None:
        route = respx.get("https://example.com/limited").mock(
            side_effect=[
                httpx.Response(429, text="rate limited"),
                httpx.Response(200, text="ok finally"),
            ]
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_text(
                client,
                "https://example.com/limited",
                max_attempts=3,
                max_backoff=0.01,
            )

        assert result == "ok finally"
        assert route.call_count == 2

    @respx.mock
    async def test_retry_on_503_then_success(self) -> None:
        route = respx.get("https://example.com/down").mock(
            side_effect=[
                httpx.Response(503, text="service unavailable"),
                httpx.Response(200, text="recovered"),
            ]
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_text(
                client,
                "https://example.com/down",
                max_attempts=3,
                max_backoff=0.01,
            )

        assert result == "recovered"
        assert route.call_count == 2

    @respx.mock
    async def test_retry_on_timeout_then_success(self) -> None:
        route = respx.get("https://example.com/slow").mock(
            side_effect=[
                httpx.ReadTimeout("timed out"),
                httpx.Response(200, text="slow but ok"),
            ]
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_text(
                client,
                "https://example.com/slow",
                max_attempts=3,
                max_backoff=0.01,
            )

        assert result == "slow but ok"
        assert route.call_count == 2

    @respx.mock
    async def test_retry_on_connect_error_then_success(self) -> None:
        route = respx.get("https://example.com/flaky").mock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                httpx.Response(200, text="reconnected"),
            ]
        )

        async with httpx.AsyncClient() as client:
            result = await fetch_text(
                client,
                "https://example.com/flaky",
                max_attempts=3,
                max_backoff=0.01,
            )

        assert result == "reconnected"
        assert route.call_count == 2

    @respx.mock
    async def test_max_retries_exceeded_persistent_503(self) -> None:
        route = respx.get("https://example.com/down").mock(
            return_value=httpx.Response(503, text="still down")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(MaxRetriesExceeded) as exc_info:
                await fetch_text(
                    client,
                    "https://example.com/down",
                    max_attempts=2,
                    max_backoff=0.01,
                )

        assert exc_info.value.url == "https://example.com/down"
        assert route.call_count == 2

    @respx.mock
    async def test_max_retries_exceeded_persistent_timeout(self) -> None:
        route = respx.get("https://example.com/timeout").mock(
            side_effect=httpx.ReadTimeout("always times out")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(MaxRetriesExceeded):
                await fetch_text(
                    client,
                    "https://example.com/timeout",
                    max_attempts=2,
                    max_backoff=0.01,
                )

        assert route.call_count == 2

    @respx.mock
    async def test_single_attempt_no_retry_on_timeout(self) -> None:
        route = respx.get("https://example.com/fail").mock(
            side_effect=httpx.ReadTimeout("fail")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(MaxRetriesExceeded):
                await fetch_text(
                    client,
                    "https://example.com/fail",
                    max_attempts=1,
                    max_backoff=0.01,
                )

        assert route.call_count == 1


# --------------------------------------------------------------------------- #
# DomainRateLimiter
# --------------------------------------------------------------------------- #


class TestDomainRateLimiter:
    async def test_no_delay_when_disabled(self) -> None:
        limiter = DomainRateLimiter(delay_seconds=0.0)
        start = time.monotonic()
        await limiter.acquire("https://example.com/a")
        await limiter.acquire("https://example.com/b")
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    async def test_enforces_delay_for_same_host(self) -> None:
        limiter = DomainRateLimiter(delay_seconds=0.12)

        start = time.monotonic()
        await limiter.acquire("https://example.com/a")
        await limiter.acquire("https://example.com/b")
        elapsed = time.monotonic() - start

        # First call is instant; second waits ~0.12s.
        assert elapsed >= 0.10

    async def test_no_delay_for_different_hosts(self) -> None:
        limiter = DomainRateLimiter(delay_seconds=0.15)

        start = time.monotonic()
        await limiter.acquire("https://alpha.com/a")
        await limiter.acquire("https://beta.com/b")
        await limiter.acquire("https://gamma.com/c")
        elapsed = time.monotonic() - start

        # All different hosts — no inter-host delay.
        assert elapsed < 0.05

    async def test_concurrent_same_host_serialises(self) -> None:
        """Three concurrent callers to the same host are serialised."""
        limiter = DomainRateLimiter(delay_seconds=0.10)
        call_times: list[float] = []

        async def worker() -> None:
            await limiter.acquire("https://example.com/resource")
            call_times.append(time.monotonic())

        await asyncio.gather(worker(), worker(), worker())

        # Each subsequent call waited ~0.1s after the previous one.
        assert len(call_times) == 3
        gaps = [call_times[i + 1] - call_times[i] for i in range(2)]
        for gap in gaps:
            assert gap >= 0.08  # allow small scheduling tolerance
