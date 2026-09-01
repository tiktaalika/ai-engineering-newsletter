"""Fetcher protocol and shared utilities.

All source-type fetchers implement the :class:`Fetcher` protocol so the
orchestration layer can treat them uniformly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

import httpx

from newsletter.models import RawRecord, Source


@runtime_checkable
class Fetcher(Protocol):
    """Interface every source-type fetcher must satisfy."""

    @property
    def fetch_types(self) -> frozenset[str]:
        """Return the set of ``fetch_type`` values this fetcher handles."""
        ...

    async def fetch(
        self,
        source: Source,
        client: httpx.AsyncClient,
        *,
        cutoff: datetime | None = None,
    ) -> list[RawRecord]:
        """Fetch raw records from *source* using the shared HTTP *client*.

        Parameters
        ----------
        source:
            The configured source to fetch from.
        client:
            A shared ``httpx.AsyncClient`` with appropriate headers/timeouts.
        cutoff:
            Optional cutoff datetime — records older than this may be
            discarded by fetchers that support it (e.g. HN Algolia).

        Returns
        -------
        list[RawRecord]:
            Zero or more unparsed raw records.
        """
        ...
