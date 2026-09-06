"""URL normalization and event deduplication (Goal 6.4).

Currently provides :func:`norm_url`; canonical event keys, token
similarity, and cross-section dedup land here with the selection stage.
"""

from __future__ import annotations

import urllib.parse


def norm_url(url: str) -> str:
    """Normalize a URL for deduplication (v1 parity).

    - lowercases the network location
    - strips the trailing path slash
    - drops the fragment
    - removes ``utm_*`` query parameters (case-insensitive prefix)
    - drops blank query values (``?foo=``)

    Idempotent: ``norm_url(norm_url(x)) == norm_url(x)``.
    """
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    kept = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            urllib.parse.urlencode(kept),
            "",
        )
    )
