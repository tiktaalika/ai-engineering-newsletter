"""URL normalization and event deduplication (Goal 6.4).

Two distinct notions of "same item" are used by the pipeline:

* **Identity** — :func:`norm_url` / :func:`dedup_key`.  Used while
  collecting, so one article reached through two feeds is stored once.
* **Same event** — :func:`is_same_event`.  Used while selecting, so two
  *different* articles about one story (different URLs, near-identical
  headlines) do not both make the digest.

Event detection combines three signals, in order: canonical URL key,
hardcoded canonical event keys for recurring stories, and token overlap.
All rules are v1 parity — PROJECT.md §3.6.
"""

from __future__ import annotations

import re
import urllib.parse

from attrs import frozen

from .models import Candidate

# --------------------------------------------------------------------------- #
# Token stop-lists (v1 parity)
# --------------------------------------------------------------------------- #

#: Words too generic to identify an event.
COMMON_EVENT_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "new",
        "of",
        "on",
        "or",
        "s",
        "says",
        "the",
        "to",
        "with",
        "report",
        "reports",
        "reported",
        "exclusive",
        "breaking",
        "news",
        "via",
    }
)

#: Outlet names that appear in headlines but carry no event identity.
SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        "reuters",
        "bbc",
        "cnbc",
        "forbes",
        "techcrunch",
        "bloomberg",
        "wsj",
        "financial",
        "times",
        "guardian",
        "yahoo",
        "finance",
        "ap",
        "axios",
        "nytimes",
        "meta",
        "openai",
    }
)

#: Minimum token length considered for event identity.
MIN_TOKEN_LENGTH: int = 3

#: Strips a trailing ``" - Outlet"`` suffix from a headline.
_SOURCE_SUFFIX_PATTERN = re.compile(r"\s+-\s+[^-]+$")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# --------------------------------------------------------------------------- #
# Token-overlap thresholds (v1 parity)
# --------------------------------------------------------------------------- #

#: Same outlet: 2 shared tokens covering ≥ 67% of the smaller headline.
SAME_SOURCE_MIN_INTERSECTION: int = 2
SAME_SOURCE_MIN_COVERAGE: float = 0.67

#: Any outlets: 5 shared tokens covering ≥ 50% of the smaller headline.
STRONG_MIN_INTERSECTION: int = 5
STRONG_MIN_COVERAGE: float = 0.5

#: Any outlets: 4 shared tokens covering ≥ 42% of the union.
UNION_MIN_INTERSECTION: int = 4
UNION_MIN_JACCARD: float = 0.42


# --------------------------------------------------------------------------- #
# Canonical event keys
# --------------------------------------------------------------------------- #


@frozen
class EventRule:
    """One recurring-story rule for :func:`canonical_event_key`.

    Attributes
    ----------
    key:
        Stable event identifier written into the candidates JSON.
    all_terms:
        Substrings that must *all* appear in the lowercased title.
    any_groups:
        Groups of alternatives — at least one term from *each* group must
        appear.  Empty means no further constraint.
    """

    key: str
    all_terms: tuple[str, ...]
    any_groups: tuple[tuple[str, ...], ...] = ()

    def matches(self, lowered_title: str) -> bool:
        if not all(term in lowered_title for term in self.all_terms):
            return False
        return all(
            any(term in lowered_title for term in group) for group in self.any_groups
        )


#: Ordered: the first matching rule wins, exactly like v1's if-chain.  Keep
#: broader rules *after* narrower ones or they will shadow them.
EVENT_RULES: tuple[EventRule, ...] = (
    EventRule(
        key="openai-ipo",
        all_terms=("openai",),
        any_groups=(
            (
                "ipo",
                "initial public",
                "go public",
                "public offering",
                "stock market",
                "s-1",
                "sec",
            ),
        ),
    ),
    EventRule(
        key="openai-anthropic-price-war",
        all_terms=("openai", "anthropic"),
        any_groups=(("price cut", "price cuts", "slashing prices", "drastic price"),),
    ),
    EventRule(
        key="visa-openai-agent-payments",
        all_terms=("visa",),
        any_groups=(
            ("openai", "chatgpt"),
            ("payment", "payments", "agentic commerce", "ai agent"),
        ),
    ),
    EventRule(
        key="mastercard-ai-agent-payments",
        all_terms=("mastercard",),
        any_groups=(
            (
                "ai agent",
                "agent payments",
                "agentic commerce",
                "micropayments",
                "machine-to-machine",
                "coinbase",
                "ripple",
                "onchain",
            ),
        ),
    ),
    EventRule(
        key="microsoft-claude-fable-access",
        all_terms=("microsoft", "claude"),
        any_groups=(
            (
                "fable",
                "employee access",
                "data retention",
                "data terms",
                "restricts",
                "limited",
            ),
        ),
    ),
    EventRule(
        key="anthropic-regulation-call",
        all_terms=("anthropic",),
        any_groups=(
            ("regulation", "government", "block dangerous", "stronger regulation"),
        ),
    ),
    EventRule(
        key="anthropic-model-restrictions-backlash",
        all_terms=("anthropic",),
        any_groups=(("walks back", "backlash", "restrictions", "sabotaged"),),
    ),
    EventRule(
        key="anthropic-export-controls-model-access",
        all_terms=("anthropic",),
        any_groups=(
            (
                "export control",
                "foreign access",
                "government order",
                "taken offline",
                "shuts down",
                "suspended",
                "security fears",
                "pulled the plug",
            ),
        ),
    ),
    EventRule(key="apple-siri-ai", all_terms=("apple", "siri")),
    EventRule(
        key="openai-ohio-data-center",
        all_terms=("openai", "data center"),
        any_groups=(("ohio", "gigawatt", "nvidia"),),
    ),
    EventRule(
        key="meta-reliance-india-data-center",
        all_terms=("meta", "reliance", "data center"),
    ),
    EventRule(
        key="thea-energy-fusion-digital-twin",
        all_terms=("thea energy",),
        any_groups=(("helios", "fusion", "surrogate", "digital twin"),),
    ),
    EventRule(
        key="synera-nvidia-engineering-agents",
        all_terms=("synera", "nvidia"),
        any_groups=(("engineering simulation", "design"),),
    ),
    EventRule(
        key="siemens-simcenter-physicsai-cfd", all_terms=("simcenter physicsai", "cfd")
    ),
)


def canonical_event_key(title: str) -> str | None:
    """Return the hardcoded event key for a recurring story, if any.

    ``None`` means "no known recurring event" and callers fall through to
    token-overlap comparison.
    """
    lowered = title.lower()
    for rule in EVENT_RULES:
        if rule.matches(lowered):
            return rule.key
    return None


# --------------------------------------------------------------------------- #
# URL / identity helpers
# --------------------------------------------------------------------------- #


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


def event_url_key(url: str) -> str:
    """Scheme + host + path (no query), lowercased — the event URL identity.

    Returns ``""`` for anything without a scheme and host, so callers can
    treat link-less records as "no URL evidence".
    """
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    ).lower()


def dedup_key(title: str, url: str) -> str:
    """Collection-time identity key: normalized URL, else lowercased title.

    Mirrors v1's ``unique_key`` so a link-less record still dedupes against
    an identical headline.
    """
    return norm_url(url) or title.strip().lower()


def event_tokens(title: str) -> set[str]:
    """Identity tokens of a headline: lowercase alphanumerics, filtered.

    A trailing ``" - Outlet"`` suffix is stripped first, then tokens of
    three or more characters survive unless they are generic words or known
    outlet names.
    """
    stripped = _SOURCE_SUFFIX_PATTERN.sub("", title.lower())
    tokens = _TOKEN_PATTERN.findall(stripped)
    return {
        token
        for token in tokens
        if len(token) >= MIN_TOKEN_LENGTH
        and token not in COMMON_EVENT_WORDS
        and token not in SOURCE_SUFFIXES
    }


# --------------------------------------------------------------------------- #
# Same-event detection
# --------------------------------------------------------------------------- #


def _shares_event_tokens(left: set[str], right: set[str], same_source: bool) -> bool:
    """Token-overlap rules (v1 parity)."""
    if not left or not right:
        return False
    intersection = left & right
    union = left | right
    smaller = min(len(left), len(right))
    shared = len(intersection)

    if same_source and shared >= SAME_SOURCE_MIN_INTERSECTION:
        if shared / max(smaller, 1) >= SAME_SOURCE_MIN_COVERAGE:
            return True
    if shared >= STRONG_MIN_INTERSECTION and shared / max(smaller, 1) >= (
        STRONG_MIN_COVERAGE
    ):
        return True
    return shared >= UNION_MIN_INTERSECTION and shared / max(len(union), 1) >= (
        UNION_MIN_JACCARD
    )


def is_same_event(left: Candidate, right: Candidate) -> bool:
    """Whether two candidates report the same underlying story.

    Checks, in order (any hit means "same event"):

    1. identical canonical URL keys;
    2. identical :func:`canonical_event_key`;
    3. headline token overlap — a looser bar when both come from the same
       outlet, since one outlet rarely publishes the same story twice.
    """
    left_url = event_url_key(left.url)
    right_url = event_url_key(right.url)
    if left_url and right_url and left_url == right_url:
        return True

    left_key = canonical_event_key(left.title)
    right_key = canonical_event_key(right.title)
    if left_key and left_key == right_key:
        return True

    return _shares_event_tokens(
        event_tokens(left.title),
        event_tokens(right.title),
        left.source.name.lower() == right.source.name.lower(),
    )
