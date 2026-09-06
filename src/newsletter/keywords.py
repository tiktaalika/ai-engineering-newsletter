"""Keyword configuration and term matching (Goals 1.4 / 6.2).

Replaces v1's ``config/keywords.json`` with a typed TOML config
(``config/keywords.toml``).  Two buckets drive the collection filter:

``general_ai``
    Broad AI news.  ``include``/``exclude`` only.
``engineering_ai``
    CAE / simulation AI.  Adds two *gates* — ``core_include`` (domain
    terms) and ``ai_include`` (AI terms) — both of which must match, so a
    pure-CFD or pure-LLM story alone does not qualify.

Matching is case-insensitive substring matching over ``"{title} {text}"``,
exactly as in v1 ``matched_terms`` / ``matches_core_terms``.
"""

from __future__ import annotations

from pathlib import Path
from tomllib import TOMLDecodeError
from tomllib import load as load_toml
from typing import Any, Literal, get_args

from attrs import field, frozen
from cattrs import structure
from cattrs.errors import ClassValidationError

from .category import canonical_category

BucketName = Literal["general_ai", "engineering_ai"]
"""Keyword bucket identifiers (canonical category names)."""


class KeywordError(Exception):
    """Raised when keyword configuration loading or validation fails."""


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

#: Bucket fields that must be lists of strings.
_LIST_FIELDS: tuple[str, ...] = ("include", "exclude", "core_include", "ai_include")

#: Every key allowed inside a bucket table, so typos are rejected.
_ALLOWED_FIELDS: frozenset[str] = frozenset(_LIST_FIELDS) | {"required_language"}


def _validate_raw(raw_data: Any, keywords_path: Path) -> None:
    """Schema-check the raw TOML before cattrs structuring (Goal 1.4).

    cattrs will happily iterate a bare string into a list of characters, and
    an absent bucket would silently fall back to empty defaults, so the shape
    is verified explicitly instead.
    """
    if not isinstance(raw_data, dict):
        raise KeywordError(f"Expected one table per keyword bucket in {keywords_path}")

    for name in get_args(BucketName):
        bucket = raw_data.get(name)
        if bucket is None:
            raise KeywordError(f"Missing keyword bucket [{name}] in {keywords_path}")
        if not isinstance(bucket, dict):
            raise KeywordError(
                f"Keyword bucket [{name}] must be a table in {keywords_path}"
            )

        unknown = {str(key) for key in bucket} - set(_ALLOWED_FIELDS)
        if unknown:
            raise KeywordError(
                f"Unknown key(s) in [{name}] of {keywords_path}: "
                f"{', '.join(sorted(unknown))}"
            )

        for key in _LIST_FIELDS:
            if key not in bucket:
                continue
            value = bucket[key]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise KeywordError(
                    f"[{name}].{key} must be a list of strings in {keywords_path}"
                )

        language = bucket.get("required_language")
        if language is not None and not isinstance(language, str):
            raise KeywordError(
                f"[{name}].required_language must be a string in {keywords_path}"
            )


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


@frozen
class KeywordFilter:
    """One keyword bucket.

    Attributes
    ----------
    include:
        Terms of which at least one must appear; the hit count feeds
        ``general_relevance`` in scoring.
    exclude:
        Terms of which *any* hit rejects the item outright (checked first).
    core_include:
        Engineering domain gate — empty means "no gate".
    ai_include:
        Engineering AI gate — empty means "no gate".
    required_language:
        Reserved for the Goal 5 language axis; the pipeline currently
        applies the English heuristic unconditionally (v1 parity).
    """

    include: list[str] = field(factory=list)
    exclude: list[str] = field(factory=list)
    core_include: list[str] = field(factory=list)
    ai_include: list[str] = field(factory=list)
    required_language: str = "en"


@frozen
class KeywordConfig:
    """Both keyword buckets, loaded from ``config/keywords.toml``."""

    general_ai: KeywordFilter = field(factory=KeywordFilter)
    engineering_ai: KeywordFilter = field(factory=KeywordFilter)

    @classmethod
    def load(cls, keywords_path: Path) -> KeywordConfig:
        """Structure and validate the TOML keyword config.

        Raises
        ------
        FileNotFoundError
            If ``keywords_path`` does not exist (mirrors
            :meth:`newsletter.Configuration.load`).
        KeywordError
            If the TOML is malformed, a bucket is missing, or a field has
            the wrong shape.
        """
        if not keywords_path.exists():
            raise FileNotFoundError(
                f"Keyword configuration file not found at: {keywords_path}"
            )

        try:
            with keywords_path.open("rb") as f:
                raw_data = load_toml(f)
        except TOMLDecodeError as e:
            raise KeywordError(f"Invalid TOML format in {keywords_path}: {e}") from e

        _validate_raw(raw_data, keywords_path)

        try:
            config = structure(raw_data, cls)
        except ClassValidationError as e:
            raise KeywordError(f"Keyword validation failed: {e}") from e

        # An empty include list would silently reject every item, so treat it
        # as a configuration error rather than a valid but useless bucket.
        for name in get_args(BucketName):
            if not config.bucket(name).include:
                raise KeywordError(
                    f"Keyword bucket {name!r} in {keywords_path} defines no "
                    "include terms"
                )
        return config

    def bucket(self, name: BucketName) -> KeywordFilter:
        """Return the filter for an explicit bucket name."""
        return self.engineering_ai if name == "engineering_ai" else self.general_ai

    def filter_for(self, category: str) -> KeywordFilter:
        """Return the filter that applies to a source/candidate category."""
        return self.bucket(keyword_bucket_name(category))


# --------------------------------------------------------------------------- #
# Bucket resolution
# --------------------------------------------------------------------------- #


def keyword_bucket_name(category: str) -> BucketName:
    """Resolve the keyword bucket for a category (v1 parity).

    ``cae_ai_engineering`` and ``engineering_ai`` both map to the
    engineering bucket; everything else uses ``general_ai``.
    """
    if canonical_category(category) == "engineering_ai":
        return "engineering_ai"
    return "general_ai"


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #


def match_terms(text: str, terms: list[str]) -> list[str]:
    """Return the ``terms`` that appear in ``text`` (case-insensitive).

    Substring matching, in the order the terms are configured, so the
    result is deterministic and mirrors v1's ``matched_terms``.
    """
    haystack = text.lower()
    return [term for term in terms if term.lower() in haystack]


def blocked_terms(text: str, exclude: list[str]) -> list[str]:
    """Return the exclusion terms present in ``text`` (case-insensitive)."""
    return match_terms(text, exclude)


def matches(text: str, keyword_filter: KeywordFilter) -> tuple[list[str], bool]:
    """Apply a bucket's exclude-then-include filter (v1 ``matched_terms``).

    Returns
    -------
    tuple[list[str], bool]:
        The matched include terms and whether the text passes.  Any
        exclusion hit short-circuits to ``([], False)``.
    """
    if blocked_terms(text, keyword_filter.exclude):
        return [], False
    hits = match_terms(text, keyword_filter.include)
    return hits, bool(hits)


def matches_core_terms(text: str, terms: list[str] | None) -> bool:
    """Gate helper: does ``text`` contain any of ``terms``?

    An empty or missing term list means "no gate" and passes, which is how
    v1 treats the ``general_ai`` bucket (it defines neither gate).
    """
    if not terms:
        return True
    return bool(match_terms(text, terms))


def passes_gates(text: str, keyword_filter: KeywordFilter) -> bool:
    """Both engineering gates must match (``core_include`` AND ``ai_include``)."""
    return matches_core_terms(text, keyword_filter.core_include) and matches_core_terms(
        text, keyword_filter.ai_include
    )
