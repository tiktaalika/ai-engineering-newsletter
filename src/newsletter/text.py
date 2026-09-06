"""Text-processing utilities (Goal 6.1).

Small, dependency-free helpers shared by every pipeline stage:

* :func:`clean_text` — HTML/entity/whitespace normalization of feed text
* :func:`language_looks_english` — the ASCII-ratio language heuristic
* :func:`entry_id` — deterministic candidate ID (LLM summary cache + dedup)
* :func:`effective_source` — resolves the real outlet behind Google News
* :func:`english_summary` — extractive two-sentence fallback summary

All are v1 parity (PROJECT.md §3.3, §5.4, §5.5).
"""

from __future__ import annotations

import hashlib
import html
import re

from .models import Candidate

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Below this many ASCII letters the language heuristic abstains (v1 parity).
MIN_LETTERS_FOR_LANGUAGE_CHECK: int = 20

#: Minimum share of ASCII characters for text to look English (v1 parity).
ENGLISH_ASCII_RATIO: float = 0.82

#: Sentences kept by :func:`english_summary` (v1 parity).
SUMMARY_SENTENCES: int = 2

#: Hard cap on the extractive summary length (v1 parity).
SUMMARY_MAX_CHARS: int = 340

#: Used when a candidate has no usable body text (v1 parity).
FALLBACK_SUMMARY: str = (
    "Selected for its relevance, source priority, recency, "
    "and cross-source/topic evidence."
)

_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #


def clean_text(value: str | None) -> str:
    """Unescape HTML, strip tags, and collapse whitespace.

    ``None`` and empty input yield ``""``.  Used for every string that
    reaches a candidate (titles, descriptions, sitemap ``<loc>`` values).
    """
    unescaped = html.unescape(value or "")
    without_tags = _TAG_PATTERN.sub(" ", unescaped)
    return _WHITESPACE_PATTERN.sub(" ", without_tags).strip()


def language_looks_english(text: str) -> bool:
    """Heuristic English check: enough letters and a high ASCII ratio.

    Deliberately conservative — short strings (titles alone, numbers,
    punctuation) return ``False`` so non-English sources are dropped
    rather than guessed at.  Becomes per-language configurable in Goal 5.2.
    """
    letters = re.findall(r"[A-Za-z]", text)
    if len(letters) < MIN_LETTERS_FOR_LANGUAGE_CHECK:
        return False
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(len(text), 1)
    return ascii_ratio > ENGLISH_ASCII_RATIO


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def entry_id(url: str, title: str) -> str:
    """Deterministic 16-char hex ID for a candidate (v1 parity).

    SHA1 prefix of the lowercased URL, falling back to the title when
    the URL is empty (e.g. link-less feed items).  Callers must pass a
    *normalized* URL (:func:`newsletter.dedup.norm_url`) so that
    equivalent links share one ID.
    """
    raw = (url or title).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Presentation helpers
# --------------------------------------------------------------------------- #


def effective_source(candidate: Candidate) -> str:
    """Resolve the outlet behind a Google News redirect (v1 parity).

    Google News items are registered under a ``Google News …`` source but
    carry the real publisher as a ``" - Publisher"`` title suffix.  Any
    other source is returned as-is; a blank name becomes ``"unknown"``.
    """
    source = candidate.source.name.strip()
    title = candidate.title.strip()
    if source.lower().startswith("google news") and " - " in title:
        inferred = title.rsplit(" - ", 1)[-1].strip()
        if inferred:
            return inferred
    return source or "unknown"


def english_summary(candidate: Candidate) -> str:
    """Extractive two-sentence English summary (v1 parity).

    Strips a leading repeat of the title, keeps the first
    :data:`SUMMARY_SENTENCES` sentences, truncates to
    :data:`SUMMARY_MAX_CHARS`, and falls back to
    :data:`FALLBACK_SUMMARY` when the body carries no text.
    """
    text = _WHITESPACE_PATTERN.sub(" ", candidate.text).strip()
    title = candidate.title.strip()
    if title and text.lower().startswith(title.lower()):
        text = text[len(title) :].strip(" -:.,")

    sentences = _SENTENCE_PATTERN.split(text)
    summary = " ".join(
        sentence for sentence in sentences[:SUMMARY_SENTENCES] if sentence
    )
    if not summary:
        return FALLBACK_SUMMARY
    if len(summary) > SUMMARY_MAX_CHARS:
        return summary[: SUMMARY_MAX_CHARS - 3].rstrip() + "..."
    return summary
