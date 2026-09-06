"""Text-processing utilities (Goal 6.1).

Currently provides the deterministic entry identifier used for candidate
IDs, the LLM summary cache, and historical dedup.  ``clean_text`` and
language helpers land here with the scoring stage.
"""

from __future__ import annotations

import hashlib


def entry_id(url: str, title: str) -> str:
    """Deterministic 16-char hex ID for a candidate (v1 parity).

    SHA1 prefix of the lowercased URL, falling back to the title when
    the URL is empty (e.g. link-less feed items).  Callers must pass a
    *normalized* URL (:func:`newsletter.dedup.norm_url`) so that
    equivalent links share one ID.
    """
    raw = (url or title).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:16]
